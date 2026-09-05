"""Idempotent chunk embedding orchestration without LLM response generation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from real_estate_agent.rag.chunking.models import DocumentChunk
from real_estate_agent.rag.chunking.pipeline import read_chunks
from real_estate_agent.rag.embeddings.models import EmbeddingRunResult
from real_estate_agent.rag.embeddings.provider import EmbeddingProvider
from real_estate_agent.rag.embeddings.repository import (
    EmbeddedChunk,
    ExistingEmbeddingState,
)


class EmbeddingPipelineError(RuntimeError):
    """Raised when the local chunk corpus is incomplete or inconsistent."""


class EmbeddingRepository(Protocol):
    """Minimal persistence contract used by the orchestration."""

    def existing_states(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, ExistingEmbeddingState]: ...

    def synchronize(
        self,
        embedded_chunks: Sequence[EmbeddedChunk],
        *,
        selected_source_ids: set[str],
        current_chunk_ids: set[str],
    ) -> int: ...


def load_chunk_corpus(
    chunk_dir: Path,
    *,
    source_ids: Sequence[str] | None = None,
) -> list[DocumentChunk]:
    """Load the selected JSONL files and reject duplicates or missing sources."""
    requested = set(source_ids or [])
    paths = sorted(chunk_dir.glob("*.jsonl"))
    if requested:
        paths = [path for path in paths if path.stem in requested]
        missing = requested - {path.stem for path in paths}
        if missing:
            raise EmbeddingPipelineError(
                "Missing chunk files for source(s): " + ", ".join(sorted(missing))
            )
    if not paths:
        raise EmbeddingPipelineError(
            f"No chunk JSONL files found in '{chunk_dir}'. Run Phase 6.3 first."
        )

    chunks: list[DocumentChunk] = []
    for path in paths:
        chunks.extend(read_chunks(path))
    chunks.sort(key=lambda chunk: (chunk.source_id, chunk.chunk_index))

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise EmbeddingPipelineError("The selected corpus contains duplicate chunk IDs.")
    return chunks


def _needs_embedding(
    chunk: DocumentChunk,
    existing: ExistingEmbeddingState | None,
    provider: EmbeddingProvider,
    force: bool,
) -> bool:
    return (
        force
        or existing is None
        or existing.content_sha256 != chunk.content_sha256
        or existing.embedding_model != provider.model
        or existing.embedding_dimensions != provider.dimensions
    )


def run_embedding_index(
    chunks: Sequence[DocumentChunk],
    provider: EmbeddingProvider,
    repository: EmbeddingRepository,
    *,
    batch_size: int = 64,
    force: bool = False,
) -> EmbeddingRunResult:
    """Embed only changed chunks, then atomically synchronize PostgreSQL."""
    ordered = sorted(chunks, key=lambda chunk: (chunk.source_id, chunk.chunk_index))
    if not ordered:
        raise EmbeddingPipelineError("The embedding corpus is empty.")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    all_ids = [chunk.chunk_id for chunk in ordered]
    if len(all_ids) != len(set(all_ids)):
        raise EmbeddingPipelineError("The embedding corpus contains duplicate chunk IDs.")
    existing = repository.existing_states(all_ids)
    pending = [
        chunk
        for chunk in ordered
        if _needs_embedding(chunk, existing.get(chunk.chunk_id), provider, force)
    ]

    generated: list[EmbeddedChunk] = []
    embedded_at = datetime.now(UTC)
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = provider.embed([chunk.text for chunk in batch])
        if len(vectors) != len(batch):
            raise EmbeddingPipelineError(
                "The embedding provider returned a different number of vectors than texts."
            )
        generated.extend(
            EmbeddedChunk(
                chunk=chunk,
                embedding=vector,
                model=provider.model,
                dimensions=provider.dimensions,
                embedded_at=embedded_at,
            )
            for chunk, vector in zip(batch, vectors, strict=True)
        )

    selected_sources = {chunk.source_id for chunk in ordered}
    deleted = repository.synchronize(
        generated,
        selected_source_ids=selected_sources,
        current_chunk_ids=set(all_ids),
    )
    return EmbeddingRunResult(
        total_chunks=len(ordered),
        embedded_chunks=len(generated),
        unchanged_chunks=len(ordered) - len(generated),
        deleted_stale_chunks=deleted,
        source_count=len(selected_sources),
        model=provider.model,
        dimensions=provider.dimensions,
    )
