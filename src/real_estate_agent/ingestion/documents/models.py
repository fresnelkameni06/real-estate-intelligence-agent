"""Typed models for the RAG source registry and download manifest.

Acquisition-only: these describe approved official sources and the provenance of
each downloaded file. No extraction, chunking or embedding happens here.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# A safe source_id: lowercase letters, digits, underscores and hyphens only.
# Explicitly rejects path separators and traversal sequences.
_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

DocumentFormat = Literal["pdf", "html"]
AuthorityLevel = Literal["normative_law", "official_guidance", "dataset_methodology"]
DownloadStatus = Literal["downloaded", "updated", "unchanged", "failed"]


class SourceEntry(BaseModel):
    """One approved official source in the version-controlled registry."""

    source_id: str
    title: str
    publisher: str
    source_page_url: str
    download_url: str
    document_format: DocumentFormat
    expected_content_types: list[str] = Field(min_length=1)
    topics: list[str] = Field(default_factory=list)
    language: str = "fr"
    jurisdiction: str | None = None
    authority_level: AuthorityLevel
    is_normative: bool = False
    publication_date: date | None = None
    source_updated_at: date | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    last_verified_at: date | None = None
    license: str | None = None
    enabled: bool = True
    notes: str | None = None

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        if not _SOURCE_ID_RE.match(value):
            raise ValueError(
                f"Unsafe source_id '{value}': use lowercase letters, digits, "
                "'_' or '-' only (no path separators or traversal)."
            )
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"Unsafe source_id '{value}': path traversal rejected.")
        return value

    @field_validator("download_url", "source_page_url")
    @classmethod
    def _validate_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError(f"Only HTTPS URLs are allowed, got: {value[:40]}")
        return value


class ManifestEntry(BaseModel):
    """Provenance and retrieval metadata for one attempted source."""

    source_id: str
    title: str
    requested_url: str
    final_url: str | None = None
    local_path: str | None = None
    retrieved_at_utc: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    status: DownloadStatus
    error: str | None = None
