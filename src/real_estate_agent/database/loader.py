"""Idempotent bulk loader for DVF/DPE processed Parquet into PostgreSQL.

Design highlights:

* bulk load via PostgreSQL COPY into a TEMP staging table (never row-by-row ORM);
* idempotence via data_load_runs: a succeeded run with the same
  (dataset, source_sha256) short-circuits to a no-op;
* separate audit transactions: the started/failed audit records are committed
  independently of the data transaction, so a rolled-back data load still leaves
  an accurate audit trail;
* atomic snapshot replacement: the target table is replaced inside one
  transaction, so a failed load leaves the previous snapshot intact;
* validation: row counts, PK uniqueness, arrondissement FK, label domain, no
  address columns.

Row counts are never hardcoded (refreshed snapshots may change).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from sqlalchemy import Engine, text

from real_estate_agent.database.mapping import (
    DPE_DB_COLUMNS,
    DVF_DB_COLUMNS,
    prepare_dpe_frame,
    prepare_dvf_frame,
)

logger = logging.getLogger(__name__)

SCHEMA = "real_estate"

DATASETS = {
    "dvf": {
        "parquet": "data/processed/dvf/dvf_residential_mutations.parquet",
        "table": "dvf_mutations",
        "columns": DVF_DB_COLUMNS,
        "pk": "id_mutation",
        "prepare": prepare_dvf_frame,
    },
    "dpe": {
        "parquet": "data/processed/dpe/dpe_diagnostics.parquet",
        "table": "dpe_diagnostics",
        "columns": DPE_DB_COLUMNS,
        "pk": "numero_dpe",
        "prepare": prepare_dpe_frame,
    },
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def file_sha256(path: Path) -> str:
    """Stream a file's SHA-256."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def already_loaded(engine: Engine, dataset_name: str, sha256: str) -> bool:
    """True if a succeeded load with this dataset+checksum already exists."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT 1 FROM {SCHEMA}.data_load_runs "
                "WHERE dataset_name = :d AND source_sha256 = :s "
                "AND status = 'succeeded' LIMIT 1"
            ),
            {"d": dataset_name, "s": sha256},
        ).first()
    return row is not None


def _insert_started_run(engine: Engine, dataset_name: str, sha256: str,
                        source_rows: int) -> int:
    """Insert a 'started' audit row in its OWN committed transaction."""
    with engine.begin() as conn:
        run_id = conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.data_load_runs "
                "(dataset_name, source_sha256, source_rows, started_at, status) "
                "VALUES (:d, :s, :n, :t, 'started') RETURNING load_run_id"
            ),
            {"d": dataset_name, "s": sha256, "n": source_rows, "t": _utc_now()},
        ).scalar_one()
    return int(run_id)


def _mark_run(engine: Engine, run_id: int, status: str,
              loaded_rows: int | None = None, notes: str | None = None) -> None:
    """Mark an audit run succeeded/failed in its OWN committed transaction."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {SCHEMA}.data_load_runs SET status = :st, "
                "loaded_rows = :lr, finished_at = :ft, notes = :nt "
                "WHERE load_run_id = :id"
            ),
            {"st": status, "lr": loaded_rows, "ft": _utc_now(),
             "nt": notes, "id": run_id},
        )


def _csv_value(v: Any) -> str:
    """Render one value for CSV COPY; any missing value becomes empty (NULL)."""
    # pd.isna handles None, float NaN, pd.NA, and NaT in one call. Guard against
    # array-like values (pd.isna would return an array) which never occur here.
    try:
        if v is None or pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _copy_into_staging(conn: Any, staging: str, columns: list[str],
                       df: pd.DataFrame) -> None:
    """COPY a DataFrame into a staging table via psycopg 3 copy()."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in df.itertuples(index=False, name=None):
        writer.writerow([_csv_value(v) for v in row])
    buf.seek(0)

    raw = conn.connection.dbapi_connection  # psycopg 3 connection
    col_list = ", ".join(columns)
    copy_sql = (
        f'COPY {staging} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL \'\')'
    )
    with raw.cursor() as cur, cur.copy(copy_sql) as cp:
        cp.write(buf.read())


def load_dataset(engine: Engine, dataset: str, repo_root: Path) -> dict[str, Any]:
    """Load one dataset idempotently. Returns a result summary."""
    spec = DATASETS[dataset]
    parquet = repo_root / spec["parquet"]
    table = spec["table"]
    columns = spec["columns"]
    pk = spec["pk"]

    if not parquet.exists():
        raise FileNotFoundError(f"Processed Parquet not found: {parquet}")

    sha256 = file_sha256(parquet)
    source_rows = pq.ParquetFile(parquet).metadata.num_rows

    # Idempotent short-circuit.
    if already_loaded(engine, table, sha256):
        logger.info("%s: snapshot already loaded (checksum match) -> no-op", dataset)
        return {"dataset": dataset, "skipped": True, "source_rows": source_rows}

    # 1) started audit (own transaction)
    run_id = _insert_started_run(engine, table, sha256, source_rows)
    started = _utc_now()

    try:
        df = pd.read_parquet(parquet)
        prepared = spec["prepare"](df)
        prepared["load_run_id"] = run_id
        load_columns = [*columns, "load_run_id"]

        with engine.begin() as conn:
            staging = f"stg_{table}"
            conn.execute(text(f"DROP TABLE IF EXISTS {staging}"))
            # Staging mirrors the target columns loaded (TEMP, dropped on commit).
            conn.execute(
                text(
                    f"CREATE TEMP TABLE {staging} "
                    f"(LIKE {SCHEMA}.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
                )
            )
            _copy_into_staging(conn, staging, load_columns, prepared[load_columns])

            # Validate staging row count.
            staged = conn.execute(text(f"SELECT count(*) FROM {staging}")).scalar_one()
            if staged != source_rows:
                raise ValueError(
                    f"Staged rows ({staged}) != source rows ({source_rows})"
                )
            # PK uniqueness in staging.
            dup = conn.execute(
                text(f"SELECT count(*) - count(DISTINCT {pk}) FROM {staging}")
            ).scalar_one()
            if dup != 0:
                raise ValueError(f"Duplicate primary keys in staging: {dup}")

            # Atomic replacement: clear target then insert from staging.
            conn.execute(text(f"DELETE FROM {SCHEMA}.{table}"))
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.{table} ({', '.join(load_columns)}) "
                    f"SELECT {', '.join(load_columns)} FROM {staging}"
                )
            )
            final = conn.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{table}")
            ).scalar_one()
            if final != source_rows:
                raise ValueError(f"Final rows ({final}) != source rows ({source_rows})")

        # 3) mark succeeded (own transaction)
        _mark_run(engine, run_id, "succeeded", loaded_rows=source_rows)
        duration = (_utc_now() - started).total_seconds()
        logger.info("%s: loaded %d rows in %.1fs", dataset, source_rows, duration)
        return {
            "dataset": dataset, "skipped": False, "source_rows": source_rows,
            "loaded_rows": source_rows, "duration_s": round(duration, 1),
            "run_id": run_id,
        }

    except Exception as exc:  # noqa: BLE001 - we re-mark and re-raise
        # 4) data transaction already rolled back; mark failed in its own tx.
        _mark_run(engine, run_id, "failed", notes=f"{type(exc).__name__}: {exc}"[:500])
        logger.error("%s: load failed and rolled back: %s", dataset, exc)
        raise
