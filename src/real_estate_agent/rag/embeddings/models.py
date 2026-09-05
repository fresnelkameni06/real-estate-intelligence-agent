"""Validated public result models for embedding and semantic retrieval."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmbeddingRunResult(BaseModel):
    """Auditable summary of one corpus-to-pgvector synchronization."""

    total_chunks: int = Field(ge=0)
    embedded_chunks: int = Field(ge=0)
    unchanged_chunks: int = Field(ge=0)
    deleted_stale_chunks: int = Field(ge=0)
    source_count: int = Field(ge=0)
    model: str
    dimensions: int = Field(gt=0)


class SearchHit(BaseModel):
    """One pgvector search result with source information for future citations."""

    chunk_id: str
    source_id: str
    chunk_index: int
    text: str
    title: str
    publisher: str
    source_page_url: str
    download_url: str
    document_format: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    topics: list[str]
    authority_level: str
    quality_flags: list[str]
    similarity: float
