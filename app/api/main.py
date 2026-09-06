"""FastAPI entry point for the real-estate intelligence application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import (
    dispose_agent_service,
    dispose_database_engine,
    dispose_rag_answer_service,
)
from app.api.errors import register_exception_handlers
from app.api.routes import agent, analytics, health, rag


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Release shared application resources on shutdown."""
    yield
    dispose_agent_service()
    dispose_rag_answer_service()
    dispose_database_engine()


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

register_exception_handlers(app)
app.include_router(health.router)
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
