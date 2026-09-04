"""Shared FastAPI dependencies.

The SQLAlchemy engine is created lazily once per process and reused through its
connection pool. No database connection is opened merely by importing the app.
"""

from __future__ import annotations

from threading import Lock

from sqlalchemy import Engine

from app.api.errors import ServiceUnavailableError
from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine

_engine: Engine | None = None
_engine_lock = Lock()


def get_database_engine() -> Engine:
    """Return the process-wide engine, creating it from DATABASE_URL if needed."""
    global _engine

    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is None:
            try:
                database_url = load_settings().require_database_url()
            except RuntimeError as exc:
                raise ServiceUnavailableError from exc
            _engine = make_engine(database_url)
    return _engine


def dispose_database_engine() -> None:
    """Dispose the shared connection pool during application shutdown."""
    global _engine

    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None
