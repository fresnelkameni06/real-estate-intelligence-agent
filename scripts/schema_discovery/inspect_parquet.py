"""Phase 3.1 — inspect the real processed Parquet schemas (design-only).

Reads the three processed Parquet files with PyArrow, reports exact column
names, Arrow types, row counts, candidate primary-key uniqueness, null rates on
key fields, and any list/object/unusual-typed columns. Prints a compact JSON
summary to stdout.

This does NOT connect to PostgreSQL and does NOT modify any file.

Run (inside venv3):
    py scripts/schema_discovery/inspect_parquet.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = REPO_ROOT / "data" / "processed"

TARGETS = {
    "dvf_mutations": PROCESSED / "dvf" / "dvf_residential_mutations.parquet",
    "dvf_units": PROCESSED / "dvf" / "dvf_residential_units.parquet",
    "dpe_diagnostics": PROCESSED / "dpe" / "dpe_diagnostics.parquet",
}

# Candidate primary keys per dataset (checked for uniqueness).
CANDIDATE_PK = {
    "dvf_mutations": "id_mutation",
    "dvf_units": None,  # component grain: no single natural PK
    "dpe_diagnostics": "numero_dpe",
}

# Key fields whose null rate matters for schema design.
KEY_FIELDS = {
    "dvf_mutations": ["id_mutation", "mutation_date", "arrondissement",
                      "mutation_value", "residential_surface"],
    "dvf_units": ["id_mutation", "arrondissement", "surface_reelle_bati"],
    "dpe_diagnostics": ["numero_dpe", "arrondissement", "diagnostic_year",
                        "etiquette_dpe_norm", "surface_habitable_logement"],
}


def _inspect(name: str, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"missing file: {path}"}

    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    n_rows = pf.metadata.num_rows

    columns = {field.name: str(field.type) for field in schema}

    # Unusual types: lists, structs, maps.
    unusual = [
        field.name for field in schema
        if any(t in str(field.type).lower() for t in ("list", "struct", "map"))
    ]

    result: dict[str, Any] = {
        "path": str(path.relative_to(REPO_ROOT)),
        "n_rows": int(n_rows),
        "n_cols": len(columns),
        "columns": columns,
        "unusual_typed_columns": unusual,
    }

    # Read the full table only for the checks we need (columns subset).
    pk = CANDIDATE_PK.get(name)
    check_cols = [c for c in (KEY_FIELDS.get(name, [])) if c in columns]
    if pk and pk in columns and pk not in check_cols:
        check_cols.append(pk)

    if check_cols:
        table = pq.read_table(path, columns=check_cols)
        df = table.to_pandas()

        if pk and pk in df.columns:
            n_unique = int(df[pk].nunique(dropna=True))
            result["candidate_pk"] = pk
            result["pk_unique_count"] = n_unique
            result["pk_is_unique"] = (n_unique == n_rows)
            result["pk_null_count"] = int(df[pk].isna().sum())
        else:
            result["candidate_pk"] = pk

        result["null_rates_pct"] = {
            c: round(df[c].isna().mean() * 100, 3) for c in check_cols
        }

    return result


def main() -> None:
    summary = {name: _inspect(name, path) for name, path in TARGETS.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
