# PostgreSQL Setup — Phase 3.2

How to create the schema, load the processed Parquet, and validate the database.

## Prerequisites

- A running PostgreSQL server (local or managed).
- Python 3.14 with `venv3` active.
- Install the database dependencies:

```powershell
py -m pip install -e ".[database]"
```

- Two databases: a development database and a **separate** test database.

## Environment variables

Set these in `.env` (never committed). See `.env.example` for placeholders.

```
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/real_estate
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/real_estate_test
```

- The `postgresql+psycopg://` scheme selects psycopg 3.
- `TEST_DATABASE_URL` must differ from `DATABASE_URL` and its database name must
  contain `test`, or integration tests refuse to run.
- If `DATABASE_URL` is missing, commands fail with a clear message. Logs never
  print the full URL or password.

## Migrations

The schema is created **only** through Alembic migrations (never by hand):

```powershell
py -m alembic upgrade head     # create real_estate schema, tables, indexes, seed
py -m alembic downgrade base   # drop everything (reversible)
```

The initial migration creates the `real_estate` schema, the four tables
(`arrondissements`, `data_load_runs`, `dvf_mutations`, `dpe_diagnostics`),
primary/foreign keys, CHECK constraints, indexes, the partial
successful-load unique index, and seeds exactly 20 arrondissements.

## Loading

```powershell
py scripts/load_postgres.py --dataset dvf
py scripts/load_postgres.py --dataset dpe
py scripts/load_postgres.py --dataset all
```

Loading is idempotent: each dataset's Parquet checksum is recorded in
`data_load_runs`. Re-running with the same snapshot is a **no-op** (skipped).

## Validation

```powershell
py scripts/validate_postgres.py
```

Checks: exactly 20 arrondissements; DVF/DPE row counts equal the source Parquet;
primary-key uniqueness; arrondissement foreign-key validity; and the absence of
any address-level column. Exit code is non-zero if any check fails.

## Idempotence behavior

- The loader computes the Parquet SHA-256 and looks for a `succeeded`
  `data_load_runs` row with the same `(dataset, checksum)`.
- If found, the load is skipped (no API/DB write).
- Snapshot replacement is **atomic**: the target table is replaced inside one
  transaction after staging validation, so a failed load leaves the previous
  snapshot intact.

## Rollback behavior

- Data load, validation and target replacement run in a single transaction; any
  failure rolls it back.
- Audit records use **separate** transactions: the `started` record is committed
  before the data transaction, and a `failed` status is written in its own
  transaction after a rollback — so the audit trail stays accurate even when the
  data load is rolled back.
- The partial unique index (`WHERE status = 'succeeded'`) lets a failed attempt
  be retried; only one succeeded load per `(dataset, checksum)` is allowed.

## Test-database safety

Integration tests (`tests/integration/`) are **skipped** unless a safe
`TEST_DATABASE_URL` is configured. They refuse to run if it is missing, equals
`DATABASE_URL`, or does not look like a test database. They never truncate, drop
or modify the development database.

```powershell
py -m pytest                 # unit tests always run; integration skipped w/o TEST db
py -m ruff check .
```

## Troubleshooting

- **"DATABASE_URL is not set"** — add it to `.env`; do not hardcode it.
- **Connection refused** — check the PostgreSQL server is running and the
  host/port are correct (the URL is not printed in full for safety).
- **Alembic "target database is not up to date"** — run `py -m alembic upgrade
  head` before loading.
- **A load was skipped unexpectedly** — a succeeded run with the same checksum
  already exists; refresh the Parquet or inspect `real_estate.data_load_runs`.
- Never share `.env` or paste full connection URLs when asking for help.
