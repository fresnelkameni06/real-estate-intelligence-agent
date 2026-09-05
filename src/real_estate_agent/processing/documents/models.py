"""Typed models for processed RAG documents.

A ProcessedDocument holds ordered DocumentElements extracted deterministically
from a raw HTML/PDF file, plus enough provenance for future RAG citations.
No chunking or embedding happens here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

ElementKind = Literal["heading", "paragraph", "list_item", "table_row", "page"]
DocumentFormat = Literal["pdf", "html"]


class DocumentElement(BaseModel):
    """One ordered piece of extracted content."""

    order: int = Field(ge=0)
    kind: ElementKind
    text: str
    page_number: int | None = None  # PDF page (1-based) when applicable
    heading_level: int | None = None  # HTML heading level 1..6 when applicable


class ProcessedDocument(BaseModel):
    """A cleaned, structured document ready for later chunking/embedding."""

    schema_version: str = SCHEMA_VERSION
    source_id: str
    title: str
    publisher: str
    source_page_url: str
    download_url: str
    document_format: DocumentFormat
    raw_sha256: str
    processed_at_utc: str
    elements: list[DocumentElement]
    total_characters: int
    extraction_warnings: list[str] = Field(default_factory=list)
