"""SQLAlchemy engine creation for the real_estate database."""

from __future__ import annotations

import logging

from sqlalchemy import Engine, create_engine

from real_estate_agent.database.config import safe_url_summary

logger = logging.getLogger(__name__)


def make_engine(url: str, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine. Logs only a credential-free summary."""
    logger.info("Connecting to database %s", safe_url_summary(url))
    # future=True is default in SQLAlchemy 2.0; psycopg 3 driver via URL scheme.
    return create_engine(url, echo=echo, pool_pre_ping=True)
