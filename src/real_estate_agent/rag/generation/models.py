"""Public models returned by the grounded RAG answer service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AnswerStyle = Literal["auto", "brief", "detailed"]


class AnswerCitation(BaseModel):
    """One retrieved passage actually cited by the generated answer."""

    citation_id: str
    chunk_id: str
    source_id: str
    title: str
    publisher: str
    url: str
    section: str
    page_start: int | None
    page_end: int | None
    similarity: float


class RagAnswerResult(BaseModel):
    """User-facing answer plus auditable provenance and retrieval metadata."""

    question: str
    answer: str
    citations: list[AnswerCitation]
    retrieved_chunks: int = Field(ge=0)
    top_similarity: float | None
    model: str
    requested_style: AnswerStyle
    grounded: bool
    insufficient_context: bool
