"""Centralized database settings.

Reads DATABASE_URL and TEST_DATABASE_URL from the environment / .env. Never logs
complete URLs or passwords. Fails clearly when a required URL is missing.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration loaded from the environment.

    DATABASE_URL is required for real operations; TEST_DATABASE_URL is only
    required by integration tests.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")
    db_schema: str = Field(default="real_estate", alias="DB_SCHEMA")

    def require_database_url(self) -> str:
        """Return DATABASE_URL or raise a clear error (no secret in the message)."""
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Add it to your environment or .env "
                "(see .env.example). Refusing to continue without a database URL."
            )
        return self.database_url

    def require_test_database_url(self) -> str:
        """Return TEST_DATABASE_URL or raise a clear error."""
        if not self.test_database_url:
            raise RuntimeError(
                "TEST_DATABASE_URL is not set. Integration tests require a "
                "dedicated test database. Refusing to run."
            )
        return self.test_database_url


def safe_url_summary(url: str) -> str:
    """Return a credential-free summary of a database URL for logging.

    Example: 'postgresql+psycopg://<user>:***@host:5432/dbname' -> 'host:5432/dbname'.
    Never returns the password or full URL.
    """
    # Strip scheme and credentials; keep only host/port/dbname.
    tail = url.split("@")[-1] if "@" in url else url
    # tail like host:port/dbname or host/dbname
    return tail


def load_settings() -> DatabaseSettings:
    """Load database settings from the environment / .env."""
    return DatabaseSettings()
