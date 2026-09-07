"""FastAPI entry point for the real-estate intelligence application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from app.api.dependencies import (
    dispose_agent_service,
    dispose_database_engine,
    dispose_rag_answer_service,
)
from app.api.errors import register_exception_handlers
from app.api.routes import agent, analytics, health, rag
from real_estate_agent.observability import (
    RequestObservabilityMiddleware,
    configure_logging,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Release shared application resources on shutdown."""
    configure_logging()
    logger.info(
        "application_started",
        extra={"event": "application_started"},
    )

    try:
        yield
    finally:
        dispose_agent_service()
        dispose_rag_answer_service()
        dispose_database_engine()
        logger.info(
            "application_stopped",
            extra={"event": "application_stopped"},
        )


app = FastAPI(
    title="Real Estate Investment Intelligence API — Paris",
    description=(
        "Aggregate, deterministic DVF and DPE analytics for the 20 Paris "
        "arrondissements plus a bounded multi-tool agent over deterministic "
        "analytics and indexed official documents. No address-level data or "
        "generated SQL is exposed."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestObservabilityMiddleware)
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")


@app.head("/health", include_in_schema=False)
async def health_head() -> Response:
    """Support uptime monitors that use the HTTP HEAD method."""
    return Response(status_code=200)
