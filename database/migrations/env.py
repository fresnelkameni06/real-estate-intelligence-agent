"""Alembic migration environment.

The database URL comes from DATABASE_URL (never stored in alembic.ini). Target
metadata is the models' metadata bound to the real_estate schema.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.database.models import SCHEMA, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Read the runtime URL from the environment. It is NOT written into the alembic
# config (configparser would choke on '%' in an encoded password); instead it is
# passed straight to the engine below.
_settings = load_settings()
_url = _settings.require_database_url()


def _include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
    """Restrict autogenerate/compare to our schema."""
    if type_ == "table" and getattr(obj, "schema", None) not in (SCHEMA, None):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL)."""
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema=SCHEMA,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live connection)."""
    connectable = make_engine(_url)
    with connectable.connect() as connection:
        # Ensure the target schema exists before Alembic creates its version
        # table there (bootstrap: the schema is otherwise created by the first
        # migration, which is too late for the version table).
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=SCHEMA,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
