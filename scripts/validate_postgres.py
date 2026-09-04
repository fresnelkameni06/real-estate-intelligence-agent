"""Validate the loaded PostgreSQL database against the source Parquet.

Checks: exactly 20 arrondissements; DVF/DPE row counts equal source Parquet;
PK uniqueness; arrondissement FK validity; no address-level columns present.

Usage:
    py scripts/validate_postgres.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import text

from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("validate_postgres")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "real_estate"

DVF_PARQUET = REPO_ROOT / "data/processed/dvf/dvf_residential_mutations.parquet"
DPE_PARQUET = REPO_ROOT / "data/processed/dpe/dpe_diagnostics.parquet"

FORBIDDEN = ("adresse_ban", "adresse_nom_voie", "adresse_numero", "nom_rue_ban")


def main() -> int:
    settings = load_settings()
    engine = make_engine(settings.require_database_url())
    results: dict[str, object] = {}
    ok = True

    with engine.connect() as conn:
        arr = conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.arrondissements")
        ).scalar_one()
        results["arrondissements"] = arr
        ok = ok and (arr == 20)

        for name, table, pk, parquet in (
            ("dvf", "dvf_mutations", "id_mutation", DVF_PARQUET),
            ("dpe", "dpe_diagnostics", "numero_dpe", DPE_PARQUET),
        ):
            db_rows = conn.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{table}")
            ).scalar_one()
            distinct_pk = conn.execute(
                text(f"SELECT count(DISTINCT {pk}) FROM {SCHEMA}.{table}")
            ).scalar_one()
            src_rows = pq.ParquetFile(parquet).metadata.num_rows if parquet.exists() else None

            # FK validity: no arrondissement value outside the dimension.
            orphan = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.{table} t "
                    f"LEFT JOIN {SCHEMA}.arrondissements a "
                    "ON t.arrondissement = a.arrondissement_number "
                    "WHERE t.arrondissement IS NOT NULL AND a.arrondissement_number IS NULL"
                )
            ).scalar_one()

            # No address-level columns in the table.
            cols = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": SCHEMA, "t": table},
            ).scalars().all()
            forbidden_present = [c for c in cols if c in FORBIDDEN]

            results[name] = {
                "db_rows": db_rows, "source_rows": src_rows,
                "distinct_pk": distinct_pk, "pk_unique": db_rows == distinct_pk,
                "rows_match_source": (src_rows is None) or (db_rows == src_rows),
                "orphan_arrondissement_fk": orphan,
                "forbidden_address_columns": forbidden_present,
            }
            ok = ok and (db_rows == distinct_pk)
            ok = ok and ((src_rows is None) or (db_rows == src_rows))
            ok = ok and (orphan == 0)
            ok = ok and (not forbidden_present)

    results["all_checks_passed"] = ok
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
