"""Idempotent processed-document to JSONL chunk corpus pipeline."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from pydantic import ValidationError

from real_estate_agent.ingestion.documents.models import SourceEntry
from real_estate_agent.processing.documents.models import ProcessedDocument
from real_estate_agent.rag.chunking.models import (
    ChunkingConfig,
    ChunkManifest,
    ChunkManifestEntry,
    DocumentChunk,
    QualityFlag,
)
from real_estate_agent.rag.chunking.splitter import ChunkingError, chunk_document


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configuration(config: ChunkingConfig) -> dict[str, int | str]:
    return config.model_dump()


def load_processed_document(path: Path) -> tuple[ProcessedDocument, str]:
    """Load, schema-validate and checksum one Phase 6.2 JSON file."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ChunkingError(f"Processed document not found or unreadable: {path}") from exc
    try:
        document = ProcessedDocument.model_validate_json(raw)
    except ValidationError as exc:
        raise ChunkingError(f"Invalid processed document '{path.name}': {exc}") from exc
    actual_characters = sum(len(element.text) for element in document.elements)
    if document.total_characters != actual_characters:
        raise ChunkingError(
            f"Invalid total_characters in '{path.name}': "
            f"recorded {document.total_characters}, actual {actual_characters}."
        )
    return document, _sha256_bytes(raw)


def load_chunk_manifest(path: Path) -> ChunkManifest | None:
    """Load an existing corpus manifest; absence is valid on the first run."""
    if not path.exists():
        return None
    try:
        return ChunkManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise ChunkingError(f"Invalid chunk manifest '{path}': {exc}") from exc


def _atomic_write_bytes(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    try:
        part.write_bytes(payload)
        part.replace(destination)
    except OSError as exc:
        raise ChunkingError(f"Atomic write failed for '{destination}': {exc}") from exc
    finally:
        part.unlink(missing_ok=True)


def _jsonl_payload(chunks: list[DocumentChunk]) -> bytes:
    lines = [chunk.model_dump_json() for chunk in chunks]
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_chunks(path: Path) -> list[DocumentChunk]:
    """Validate every JSONL record, including contiguous source-local indexes."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        chunks = [DocumentChunk.model_validate_json(line) for line in lines if line.strip()]
    except (OSError, ValidationError) as exc:
        raise ChunkingError(f"Invalid chunk JSONL '{path}': {exc}") from exc
    if not chunks:
        raise ChunkingError(f"Chunk JSONL is empty: {path}")
    if [chunk.chunk_index for chunk in chunks] != list(range(len(chunks))):
        raise ChunkingError(f"Non-contiguous chunk indexes in '{path}'.")
    source_ids = {chunk.source_id for chunk in chunks}
    if len(source_ids) != 1:
        raise ChunkingError(f"Multiple sources mixed in '{path}'.")
    return chunks


def _quality_flags(chunks: list[DocumentChunk]) -> list[QualityFlag]:
    return list(dict.fromkeys(flag for chunk in chunks for flag in chunk.quality_flags))


def _entry_from_chunks(
    *,
    source: SourceEntry,
    processed_sha256: str,
    raw_sha256: str,
    output_path: Path,
    output_path_label: str,
    output_sha256: str,
    config: ChunkingConfig,
    chunks: list[DocumentChunk],
    status: str,
) -> ChunkManifestEntry:
    sizes = [chunk.character_count for chunk in chunks]
    return ChunkManifestEntry(
        source_id=source.source_id,
        processed_document_sha256=processed_sha256,
        raw_sha256=raw_sha256,
        output_path=output_path_label,
        output_sha256=output_sha256,
        chunking_version=config.chunking_version,
        configuration=_configuration(config),
        chunk_count=len(chunks),
        character_count=sum(sizes),
        minimum_chunk_size=min(sizes),
        maximum_chunk_size=max(sizes),
        average_chunk_size=round(fmean(sizes), 2),
        quality_flags=_quality_flags(chunks),
        status=status,
        error=None,
    )


def _failed_entry(
    source: SourceEntry,
    config: ChunkingConfig,
    error: str,
    output_path_label: str,
) -> ChunkManifestEntry:
    return ChunkManifestEntry(
        source_id=source.source_id,
        output_path=output_path_label,
        chunking_version=config.chunking_version,
        configuration=_configuration(config),
        status="failed",
        error=error,
    )


def process_source(
    source: SourceEntry,
    processed_dir: Path,
    output_dir: Path,
    config: ChunkingConfig,
    *,
    existing_entry: ChunkManifestEntry | None = None,
    force: bool = False,
    output_path_label: str | None = None,
) -> tuple[dict[str, Any], ChunkManifestEntry]:
    """Chunk one source, returning a CLI-friendly result and manifest entry."""
    processed_path = processed_dir / f"{source.source_id}.json"
    output_path = output_dir / f"{source.source_id}.jsonl"
    label = output_path_label or output_path.as_posix()
    try:
        document, processed_sha256 = load_processed_document(processed_path)
        if document.source_id != source.source_id:
            raise ChunkingError("Processed document and registry source IDs differ.")

        unchanged = (
            not force
            and existing_entry is not None
            and existing_entry.status != "failed"
            and existing_entry.processed_document_sha256 == processed_sha256
            and existing_entry.raw_sha256 == document.raw_sha256
            and existing_entry.chunking_version == config.chunking_version
            and existing_entry.configuration == _configuration(config)
            and output_path.is_file()
            and existing_entry.output_sha256 == _sha256_file(output_path)
        )
        if unchanged:
            chunks = read_chunks(output_path)
            entry = existing_entry.model_copy(update={"status": "unchanged", "error": None})
            return _result(entry), entry

        chunks = chunk_document(document, source, config)
        payload = _jsonl_payload(chunks)
        output_existed = output_path.exists()
        _atomic_write_bytes(output_path, payload)
        output_sha256 = _sha256_bytes(payload)
        # Validate what was actually persisted, not only the in-memory objects.
        persisted = read_chunks(output_path)
        if [chunk.chunk_id for chunk in persisted] != [chunk.chunk_id for chunk in chunks]:
            raise ChunkingError(f"Persisted chunk verification failed for '{source.source_id}'.")
        status = "updated" if output_existed else "chunked"
        entry = _entry_from_chunks(
            source=source,
            processed_sha256=processed_sha256,
            raw_sha256=document.raw_sha256,
            output_path=output_path,
            output_path_label=label,
            output_sha256=output_sha256,
            config=config,
            chunks=persisted,
            status=status,
        )
        return _result(entry), entry
    except ChunkingError as exc:
        entry = _failed_entry(source, config, str(exc), label)
        return _result(entry), entry


def _result(entry: ChunkManifestEntry) -> dict[str, Any]:
    return {
        "source_id": entry.source_id,
        "status": entry.status,
        "chunk_count": entry.chunk_count,
        "minimum_chunk_size": entry.minimum_chunk_size,
        "average_chunk_size": entry.average_chunk_size,
        "maximum_chunk_size": entry.maximum_chunk_size,
        "quality_flags": entry.quality_flags,
        "error": entry.error,
    }


def write_chunk_manifest(
    path: Path,
    entries: list[ChunkManifestEntry],
    config: ChunkingConfig,
) -> ChunkManifest:
    """Atomically write deterministic source ordering and aggregate statistics."""
    ordered = sorted(entries, key=lambda entry: entry.source_id)
    successful = [entry for entry in ordered if entry.status != "failed"]
    manifest = ChunkManifest(
        generated_at_utc=_utc_now_iso(),
        chunking_version=config.chunking_version,
        configuration=_configuration(config),
        sources=ordered,
        total_sources=len(successful),
        total_chunks=sum(entry.chunk_count for entry in successful),
        total_characters=sum(entry.character_count for entry in successful),
    )
    _atomic_write_bytes(path, (manifest.model_dump_json(indent=2) + "\n").encode("utf-8"))
    return manifest


def run_chunking(
    sources: list[SourceEntry],
    processed_dir: Path,
    output_dir: Path,
    config: ChunkingConfig,
    *,
    force: bool = False,
    output_root: Path | None = None,
) -> tuple[list[dict[str, Any]], ChunkManifest]:
    """Process selected sources while preserving non-selected manifest entries."""
    manifest_path = output_dir / "manifest.json"
    existing_manifest = load_chunk_manifest(manifest_path)
    merged = {
        entry.source_id: entry
        for entry in (existing_manifest.sources if existing_manifest else [])
    }
    results: list[dict[str, Any]] = []
    for source in sources:
        output_path = output_dir / f"{source.source_id}.jsonl"
        if output_root is not None:
            try:
                label = output_path.relative_to(output_root).as_posix()
            except ValueError:
                label = output_path.as_posix()
        else:
            label = output_path.as_posix()
        result, entry = process_source(
            source,
            processed_dir,
            output_dir,
            config,
            existing_entry=merged.get(source.source_id),
            force=force,
            output_path_label=label,
        )
        merged[source.source_id] = entry
        results.append(result)
    manifest = write_chunk_manifest(manifest_path, list(merged.values()), config)
    return results, manifest
