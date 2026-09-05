"""Validated models for deterministic RAG chunks and their corpus manifest."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CHUNK_SCHEMA_VERSION = "1.0"
DEFAULT_CHUNKING_VERSION = "semantic-char-v1"
QualityFlag = Literal["limited_source_content", "pathological_token"]


class ChunkingConfig(BaseModel):
    """Provider-neutral character limits used by the semantic splitter."""

    target_characters: int = Field(default=1400, ge=200)
    maximum_characters: int = Field(default=1800, ge=300)
    overlap_characters: int = Field(default=200, ge=0)
    minimum_chunk_characters: int = Field(default=120, ge=1)
    short_document_warning_threshold: int = Field(default=1000, ge=1)
    chunking_version: str = DEFAULT_CHUNKING_VERSION

    @model_validator(mode="after")
    def validate_limits(self) -> ChunkingConfig:
        if self.minimum_chunk_characters >= self.target_characters:
            raise ValueError("minimum_chunk_characters must be below target_characters")
        if self.target_characters > self.maximum_characters:
            raise ValueError("target_characters must not exceed maximum_characters")
        if self.overlap_characters >= self.target_characters:
            raise ValueError("overlap_characters must be below target_characters")
        return self


class DocumentChunk(BaseModel):
    """One self-contained passage ready for later embedding and retrieval."""

    schema_version: str = CHUNK_SCHEMA_VERSION
    chunking_version: str
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    character_count: int = Field(ge=1)
    word_count: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str
    publisher: str
    source_page_url: str
    download_url: str
    document_format: Literal["pdf", "html"]
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    topics: list[str] = Field(default_factory=list)
    language: str
    jurisdiction: str | None = None
    authority_level: str
    is_normative: bool
    effective_from: date | None = None
    effective_until: date | None = None
    quality_flags: list[QualityFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_derived_fields(self) -> DocumentChunk:
        if self.character_count != len(self.text):
            raise ValueError("character_count must equal the exact chunk text length")
        if self.word_count != len(self.text.split()):
            raise ValueError("word_count must equal the chunk text word count")
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ChunkManifestEntry(BaseModel):
    """Processing state and quality statistics for one source."""

    source_id: str
    processed_document_sha256: str | None = None
    raw_sha256: str | None = None
    output_path: str | None = None
    output_sha256: str | None = None
    chunking_version: str
    configuration: dict[str, int | str]
    chunk_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    minimum_chunk_size: int = Field(default=0, ge=0)
    maximum_chunk_size: int = Field(default=0, ge=0)
    average_chunk_size: float = Field(default=0, ge=0)
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    status: Literal["chunked", "updated", "unchanged", "failed"]
    error: str | None = None


class ChunkManifest(BaseModel):
    """Auditable inventory of the complete chunk corpus."""

    schema_version: str = CHUNK_SCHEMA_VERSION
    generated_at_utc: str
    chunking_version: str
    configuration: dict[str, int | str]
    sources: list[ChunkManifestEntry]
    total_sources: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    total_characters: int = Field(ge=0)
