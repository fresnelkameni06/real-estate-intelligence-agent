"""Safety guard for integration tests that touch a real database.

Refuses to run unless TEST_DATABASE_URL is set, is different from DATABASE_URL,
and clearly looks like a test database. Never truncates or drops the dev DB.
"""

from __future__ import annotations

from real_estate_agent.database.config import DatabaseSettings


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when the test database configuration is missing or unsafe."""


def resolve_safe_test_url(settings: DatabaseSettings) -> str:
    """Return a validated TEST_DATABASE_URL or raise UnsafeTestDatabaseError."""
    test_url = settings.test_database_url
    dev_url = settings.database_url

    if not test_url:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL is not set; refusing to run integration tests."
        )
    if dev_url and test_url == dev_url:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL must differ from DATABASE_URL; refusing to run."
        )
    # Must clearly look like a test database.
    dbname = test_url.rsplit("/", 1)[-1].lower()
    if "test" not in dbname:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL does not look like a test database "
            "(its name must contain 'test'); refusing to run."
        )
    return test_url
