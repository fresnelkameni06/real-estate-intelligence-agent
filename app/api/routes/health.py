"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, text

from app.api.dependencies import get_database_engine
from app.api.errors import ServiceUnavailableError
from app.api.schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["service"])
EngineDependency = Annotated[Engine, Depends(get_database_engine)]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API liveness",
)
def health() -> HealthResponse:
    """Return immediately when the API process is alive."""
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Check PostgreSQL readiness",
    responses={503: {"description": "Database unavailable"}},
)
def readiness(engine: EngineDependency) -> ReadinessResponse:
    """Execute a lightweight query to verify database connectivity."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except Exception as exc:
        raise ServiceUnavailableError from exc
    return ReadinessResponse()
