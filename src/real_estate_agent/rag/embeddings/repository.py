"""Persistence and exact cosine search over PostgreSQL/pgvector."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from real_estate_agent.database.models import RagDocumentChunk
from real_estate_agent.rag.chunking.models import DocumentChunk
from real_estate_agent.rag.embeddings.models import SearchHit


@dataclass(frozen=True)
class ExistingEmbeddingState:
    """Fields needed to decide whether an API call can be skipped."""

    chunk_id: str
    content_sha256: str
    embedding_model: str
    embedding_dimensions: int


@dataclass(frozen=True)
class EmbeddedChunk:
    """A validated chunk paired with its generated vector."""

    chunk: DocumentChunk
    embedding: list[float]
    model: str
    dimensions: int
    embedded_at: datetime


class PgVectorRepository:
    """Database boundary for RAG indexing and retrieval."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def existing_states(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, ExistingEmbeddingState]:
        if not chunk_ids:
            return {}
        statement = select(
            RagDocumentChunk.chunk_id,
            RagDocumentChunk.content_sha256,
            RagDocumentChunk.embedding_model,
            RagDocumentChunk.embedding_dimensions,
        ).where(RagDocumentChunk.chunk_id.in_(list(chunk_ids)))
        with Session(self._engine) as session:
            rows = session.execute(statement).all()
        return {
            row.chunk_id: ExistingEmbeddingState(
                chunk_id=row.chunk_id,
                content_sha256=row.content_sha256,
                embedding_model=row.embedding_model,
                embedding_dimensions=row.embedding_dimensions,
            )
            for row in rows
        }

    @staticmethod
    def _record(item: EmbeddedChunk) -> dict[str, object]:
        chunk = item.chunk
        return {
            "chunk_id": chunk.chunk_id,
            "source_id": chunk.source_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "character_count": chunk.character_count,
            "word_count": chunk.word_count,
            "content_sha256": chunk.content_sha256,
            "raw_sha256": chunk.raw_sha256,
            "chunking_version": chunk.chunking_version,
            "title": chunk.title,
            "publisher": chunk.publisher,
            "source_page_url": chunk.source_page_url,
            "download_url": chunk.download_url,
            "document_format": chunk.document_format,
            "heading_path": chunk.heading_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "topics": chunk.topics,
            "language": chunk.language,
            "jurisdiction": chunk.jurisdiction,
            "authority_level": chunk.authority_level,
            "is_normative": chunk.is_normative,
            "effective_from": chunk.effective_from,
            "effective_until": chunk.effective_until,
            "quality_flags": chunk.quality_flags,
            "embedding_model": item.model,
            "embedding_dimensions": item.dimensions,
            "embedding": item.embedding,
            "embedded_at": item.embedded_at,
        }

    def synchronize(
        self,
        embedded_chunks: Sequence[EmbeddedChunk],
        *,
        selected_source_ids: set[str],
        current_chunk_ids: set[str],
    ) -> int:
        """Atomically remove stale selected chunks and upsert new embeddings."""
        if not selected_source_ids:
            return 0
        table = RagDocumentChunk.__table__
        with self._engine.begin() as connection:
            stale = delete(table).where(table.c.source_id.in_(selected_source_ids))
            if current_chunk_ids:
                stale = stale.where(table.c.chunk_id.not_in(current_chunk_ids))
            deleted = connection.execute(stale).rowcount or 0

            records = [self._record(item) for item in embedded_chunks]
            if records:
                statement = pg_insert(table).values(records)
                update_columns = {
                    column.name: getattr(statement.excluded, column.name)
                    for column in table.columns
                    if column.name != "chunk_id"
                }
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[table.c.chunk_id],
                        set_=update_columns,
                    )
                )
        return deleted

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        source_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        vector = [float(value) for value in query_embedding]
        if len(vector) != 1536 or not all(math.isfinite(value) for value in vector):
            raise ValueError("The query embedding must contain 1536 finite values.")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20.")

        distance = RagDocumentChunk.embedding.cosine_distance(vector)
        statement = select(RagDocumentChunk, distance.label("distance")).order_by(distance)
        if source_ids:
            statement = statement.where(RagDocumentChunk.source_id.in_(list(source_ids)))
        statement = statement.limit(top_k)

        with Session(self._engine) as session:
            rows = session.execute(statement).all()
        return [
            SearchHit(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                title=chunk.title,
                publisher=chunk.publisher,
                source_page_url=chunk.source_page_url,
                download_url=chunk.download_url,
                document_format=chunk.document_format,
                heading_path=list(chunk.heading_path),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                topics=list(chunk.topics),
                authority_level=chunk.authority_level,
                quality_flags=list(chunk.quality_flags),
                similarity=max(-1.0, min(1.0, 1.0 - float(row_distance))),
            )
            for chunk, row_distance in rows
        ]
