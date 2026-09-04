"""FastAPI entry point for the real-estate intelligence application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import dispose_database_engine
from app.api.errors import register_exception_handlers
from app.api.routes import analytics, health


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Release the shared database connection pool on shutdown."""
    yield
    dispose_database_engine()


app = FastAPI(
    title="Real Estate Investment Intelligence API — Paris",
    description=(
        "Aggregate, deterministic DVF and DPE analytics for the 20 Paris "
        "arrondissements. No address-level data or generated SQL is exposed."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(health.router)
app.include_router(analytics.router, prefix="/api/v1")
