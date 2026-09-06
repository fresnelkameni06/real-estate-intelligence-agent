"""Small HTTP-specific response schemas.

Analytics responses reuse the typed models from the deterministic analytics
engine; this module contains only transport-level health and error contracts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from real_estate_agent.agent.models import ConversationMessage
from real_estate_agent.rag.generation.models import AnswerStyle


class HealthResponse(BaseModel):
    """Process liveness response; it deliberately does not query PostgreSQL."""

    status: Literal["ok"] = "ok"
    service: str = "real-estate-intelligence-api"
    version: str = "0.1.0"


class ReadinessResponse(BaseModel):
    """Database readiness response."""

    status: Literal["ready"] = "ready"
    database: Literal["reachable"] = "reachable"


class ErrorBody(BaseModel):
    """Stable public error body that never contains credentials or SQL."""

    code: str
    message: str
    details: list[dict[str, object]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Envelope used by controlled API errors."""

    error: ErrorBody


class RagAnswerRequest(BaseModel):
    """One bounded documentary question submitted by the dashboard."""

    question: str = Field(min_length=1, max_length=2_000)
    style: AnswerStyle = "auto"

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class AgentChatRequest(BaseModel):
    """One message plus bounded session history for the multi-tool agent."""

    message: str = Field(min_length=1, max_length=2_000)
    history: list[ConversationMessage] = Field(default_factory=list, max_length=12)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value
