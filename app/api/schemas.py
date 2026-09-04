"""Small HTTP-specific response schemas.

Analytics responses reuse the typed models from the deterministic analytics
engine; this module contains only transport-level health and error contracts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
