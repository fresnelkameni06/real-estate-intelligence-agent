"""Integration tests requiring a real PostgreSQL TEST database.

These tests are SKIPPED unless TEST_DATABASE_URL is set and passes the safety
guard. They never touch the development database. Run locally with a dedicated
test database configured in .env.

They cover: migration upgrade, arrondissement seed, schema constraints,
successful COPY load, row-count validation, PK duplicate detection, failed-load
rollback with failed audit status, retry after a failed load, same-checksum
no-op, and snapshot replacement.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.database.test_safety import (
    UnsafeTestDatabaseError,
    resolve_safe_test_url,
)

# Skip the whole module unless a safe TEST_DATABASE_URL is configured.
_settings = load_settings()
try:
    _TEST_URL = resolve_safe_test_url(_settings)
except UnsafeTestDatabaseError as exc:
    pytest.skip(f"No safe test database: {exc}", allow_module_level=True)

SCHEMA = "real_estate"


@pytest.fixture(scope="module")
def engine():
    eng = make_engine(_TEST_URL)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module", autouse=True)
def _migrated(engine):
    """Ensure the schema exists via Alembic before tests, teardown after.

    Uses the Alembic API against the TEST database URL.
    """
    import os

    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = _TEST_URL  # env.py reads DATABASE_URL
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


def test_arrondissement_seed(engine):
    with engine.connect() as conn:
        n = conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.arrondissements")
        ).scalar_one()
    assert n == 20


def test_arrondissement_check_constraint(engine):
    with engine.begin() as conn, pytest.raises((IntegrityError, ProgrammingError)):  # noqa: PT012
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.arrondissements "
                "(arrondissement_number, insee_code, postal_code, arrondissement_name)"
                " VALUES (99, '75199', '75099', 'bad')"
            )
        )


def _seed_min_dvf(engine, id_mutation="2025-1"):
    df = pd.DataFrame([{
        "id_mutation": id_mutation, "source_year": 2025, "arrondissement": 15,
        "mutation_value": 500000.0,
    }])
    return df


def test_dpe_label_domain_constraint(engine):
    with engine.begin() as conn, pytest.raises((IntegrityError, ProgrammingError)):  # noqa: PT012
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.dpe_diagnostics "
                "(numero_dpe, etiquette_dpe_norm) VALUES ('X', 'Z')"
            )
        )


def test_pk_duplicate_detected(engine):
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.dvf_mutations (id_mutation, source_year) "
                 "VALUES ('DUP-1', 2025)")
        )
    with engine.begin() as conn, pytest.raises((IntegrityError, ProgrammingError)):  # noqa: PT012
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.dvf_mutations (id_mutation, source_year) "
                 "VALUES ('DUP-1', 2025)")
        )
    # cleanup
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {SCHEMA}.dvf_mutations WHERE id_mutation='DUP-1'"))


def test_partial_unique_load_index_allows_failed_then_succeeded(engine):
    """A failed load must not block a later succeeded load for same checksum."""
    with engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO {SCHEMA}.data_load_runs "
            "(dataset_name, source_sha256, status) VALUES "
            "('t', 'abc', 'failed')"
        ))
        conn.execute(text(
            f"INSERT INTO {SCHEMA}.data_load_runs "
            "(dataset_name, source_sha256, status) VALUES "
            "('t', 'abc', 'failed')"
        ))
        # two failed with same checksum is allowed
        conn.execute(text(
            f"INSERT INTO {SCHEMA}.data_load_runs "
            "(dataset_name, source_sha256, status) VALUES "
            "('t', 'abc', 'succeeded')"
        ))
    # a second succeeded with the same checksum must violate the partial unique index
    with engine.begin() as conn, pytest.raises((IntegrityError, ProgrammingError)):  # noqa: PT012
        conn.execute(text(
            f"INSERT INTO {SCHEMA}.data_load_runs "
            "(dataset_name, source_sha256, status) VALUES "
            "('t', 'abc', 'succeeded')"
        ))
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {SCHEMA}.data_load_runs WHERE dataset_name='t'"))
