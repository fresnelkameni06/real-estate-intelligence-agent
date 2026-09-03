"""Deterministic DVF transformations for the Paris residential V1 dataset.

Pipeline, per year then combined:

    load (explicit UTF-8, typed) -> validate schema/encoding
        -> add lineage -> exact-duplicate handling (working copy only)
        -> residential component table
        -> mutation-level reconstruction
        -> price-per-m2 eligibility

Key domain rules (confirmed during Phase 1 discovery):

* one raw row is not one transaction; a mutation (``id_mutation``) can span
  several rows (multiple lots, dependencies, several dwellings, commercial
  units);
* ``valeur_fonciere`` is carried at mutation grain, so it must never be summed
  across a mutation's rows;
* ``residential_unit_count`` is the number of residential component ROWS per
  mutation after exact-row deduplication -- NOT ``nunique`` of ``type_local``
  (two apartments are two units even though the type is identical).
"""

from __future__ import annotations

import gzip
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Identifier columns kept as nullable strings.
ID_COLUMNS = [
    "id_mutation",
    "code_postal",
    "code_commune",
    "code_departement",
    "id_parcelle",
    "code_type_local",
    "adresse_code_voie",
    "numero_disposition",
]

# Numeric measurement columns.
NUMERIC_COLUMNS = [
    "valeur_fonciere",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "surface_terrain",
    "longitude",
    "latitude",
    "nombre_lots",
]

# Required core columns that must be present every year.
REQUIRED_COLUMNS = [
    "id_mutation",
    "date_mutation",
    "nature_mutation",
    "valeur_fonciere",
    "code_commune",
    "code_departement",
    "id_parcelle",
    "type_local",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "longitude",
    "latitude",
]

RESIDENTIAL_TYPES = ("Appartement", "Maison")
DEPENDENCY_TYPE = "Dépendance"
COMMERCIAL_TYPE = "Local industriel. commercial ou assimilé"
SALE_NATURE = "Vente"

# Expected correctly-decoded French forms; used to sanity-check encoding.
EXPECTED_FRENCH_FORMS = ("Vente", "Échange", "Dépendance", "Appartement", "Maison")

_REPLACEMENT_CHAR = "\ufffd"
_MOJIBAKE_MARKERS = ("Θ", "Φ", "Γ", "α", "Ã©", "Ã¨", "Ã ")

# Address-level columns intentionally dropped from processed outputs.
ADDRESS_COLUMNS = [
    "adresse_numero",
    "adresse_suffixe",
    "adresse_nom_voie",
    "adresse_code_voie",
    "ancien_id_parcelle",
    "ancien_code_commune",
    "ancien_nom_commune",
    "nom_commune",
]


class SchemaError(RuntimeError):
    """Raised when required columns are missing or French values look corrupt."""


def _id_series_to_str(series: pd.Series) -> pd.Series:
    """Coerce an identifier column to clean strings (no float ``.0``, keep NA)."""
    out = series.astype("string")
    mask = out.notna()
    out.loc[mask] = out.loc[mask].str.replace(r"\.0$", "", regex=True)
    return out


def load_dvf_csv(path: Path) -> pd.DataFrame:
    """Load one compressed DVF CSV with explicit UTF-8 and correct dtypes."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        df = pd.read_csv(
            fh,
            dtype={col: "string" for col in ID_COLUMNS},
            low_memory=False,
        )
    for col in ID_COLUMNS:
        if col in df.columns:
            df[col] = _id_series_to_str(df[col])
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "date_mutation" in df.columns:
        df["date_mutation"] = pd.to_datetime(df["date_mutation"], errors="coerce")
    return df


def detect_encoding_corruption(df: pd.DataFrame) -> dict[str, Any]:
    """Detect replacement chars / mojibake in decoded categorical text."""
    samples: list[str] = []
    for c in ("nature_mutation", "type_local", "nature_culture"):
        if c in df.columns:
            samples.extend(str(v) for v in df[c].dropna().unique().tolist())
    joined = " ".join(samples)
    replacement = _REPLACEMENT_CHAR in joined
    markers = sorted({m for m in _MOJIBAKE_MARKERS if m in joined})
    return {
        "replacement_char_present": replacement,
        "mojibake_markers_found": markers,
        "looks_clean": (not replacement) and (not markers),
    }


def validate_schema(df: pd.DataFrame, year: int) -> dict[str, Any]:
    """Validate required columns and encoding; raise SchemaError on failure."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    encoding = detect_encoding_corruption(df)
    if missing:
        raise SchemaError(f"Year {year}: missing required columns: {missing}")
    if not encoding["looks_clean"]:
        raise SchemaError(f"Year {year}: encoding corruption detected: {encoding}")
    return {
        "year": year,
        "columns": list(df.columns),
        "missing_required": missing,
        "encoding": encoding,
    }


def add_lineage(df: pd.DataFrame, year: int, source_file: str, sha256: str) -> pd.DataFrame:
    """Attach data-lineage columns to every row."""
    out = df.copy()
    out["source_year"] = year
    out["source_file"] = source_file
    out["source_sha256"] = sha256
    return out


def handle_exact_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return a deduplicated working copy and duplicate statistics.

    Raw data is never modified; this operates on the in-memory working frame.
    """
    before = int(len(df))
    dup_mask = df.duplicated(keep="first")
    duplicates = int(dup_mask.sum())
    deduped = df.loc[~dup_mask].copy()
    stats = {
        "rows_before_dedup": before,
        "exact_duplicates": duplicates,
        "rows_after_dedup": int(len(deduped)),
    }
    return deduped, stats


def derive_arrondissement(code_commune: pd.Series) -> pd.Series:
    """Derive the arrondissement (1-20) from a valid Paris INSEE code 75101-75120.

    Returns a nullable integer series; invalid/unknown codes become <NA>.
    """
    valid = {f"751{n:02d}": n for n in range(1, 21)}
    return code_commune.map(valid).astype("Int64")


def build_residential_components(df: pd.DataFrame) -> pd.DataFrame:
    """One row per residential component (Vente + Appartement/Maison)."""
    mask = (df["nature_mutation"] == SALE_NATURE) & (
        df["type_local"].isin(RESIDENTIAL_TYPES)
    )
    res = df.loc[mask].copy()
    res["arrondissement"] = derive_arrondissement(res["code_commune"])

    keep = [
        "id_mutation", "date_mutation", "valeur_fonciere", "type_local",
        "surface_reelle_bati", "nombre_pieces_principales", "code_commune",
        "code_postal", "arrondissement", "id_parcelle", "longitude", "latitude",
        "source_year", "source_file", "source_sha256",
    ]
    if "nombre_lots" in res.columns:
        keep.insert(-3, "nombre_lots")
    keep = [c for c in keep if c in res.columns]
    return res[keep].reset_index(drop=True)


def _component_counts(mutation_rows: pd.DataFrame) -> dict[str, int]:
    """Count component types within one mutation's deduplicated rows."""
    types = mutation_rows["type_local"]
    apartment = int((types == "Appartement").sum())
    house = int((types == "Maison").sum())
    dependency = int((types == DEPENDENCY_TYPE).sum())
    commercial = int((types == COMMERCIAL_TYPE).sum())
    residential = apartment + house
    return {
        "residential_unit_count": residential,
        "apartment_count": apartment,
        "house_count": house,
        "dependency_count": dependency,
        "commercial_unit_count": commercial,
        "total_component_count": int(len(mutation_rows)),
    }


def build_mutations(deduped: pd.DataFrame) -> pd.DataFrame:
    """One row per residential id_mutation with reconstructed grain.

    A mutation is "residential" if it contains at least one residential
    (Appartement/Maison) sale row. ``residential_unit_count`` is the count of
    residential component ROWS -- never ``nunique`` of the type label.
    """
    sales = deduped.loc[deduped["nature_mutation"] == SALE_NATURE].copy()
    sales["arrondissement"] = derive_arrondissement(sales["code_commune"])

    # Mutations that contain >=1 residential unit.
    is_res_row = sales["type_local"].isin(RESIDENTIAL_TYPES)
    residential_mutation_ids = sales.loc[is_res_row, "id_mutation"].unique()

    records: list[dict[str, Any]] = []
    grouped = sales[sales["id_mutation"].isin(residential_mutation_ids)].groupby(
        "id_mutation", dropna=False
    )
    for mutation_id, rows in grouped:
        counts = _component_counts(rows)

        # Mutation value: carried at mutation grain -> consistency check.
        values = rows["valeur_fonciere"].dropna().unique()
        value_consistent = len(values) <= 1
        mutation_value = float(values[0]) if len(values) == 1 else None

        # Distinct parcels.
        distinct_parcels = int(rows["id_parcelle"].nunique(dropna=True))

        # Geographical consistency across the mutation's rows.
        communes = rows["code_commune"].dropna().unique()
        geo_consistent = len(communes) == 1
        arr_values = rows["arrondissement"].dropna().unique()
        arrondissement = int(arr_values[0]) if len(arr_values) == 1 else None

        # Residential surface / rooms are only meaningful when a single unit.
        res_rows = rows[rows["type_local"].isin(RESIDENTIAL_TYPES)]
        single_unit = counts["residential_unit_count"] == 1
        if single_unit and len(res_rows) == 1:
            surface = res_rows["surface_reelle_bati"].iloc[0]
            rooms = res_rows["nombre_pieces_principales"].iloc[0]
            res_surface = float(surface) if pd.notna(surface) else None
            res_rooms = float(rooms) if pd.notna(rooms) else None
            rtype = res_rows["type_local"].iloc[0]
            lon_vals = res_rows["longitude"].dropna().unique()
            lat_vals = res_rows["latitude"].dropna().unique()
            lon = float(lon_vals[0]) if len(lon_vals) == 1 else None
            lat = float(lat_vals[0]) if len(lat_vals) == 1 else None
        else:
            res_surface = res_rooms = None
            rtype = None
            lon = lat = None

        dates = rows["date_mutation"].dropna().unique()
        mutation_date = pd.Timestamp(dates[0]) if len(dates) == 1 else None

        records.append({
            "id_mutation": mutation_id,
            **counts,
            "distinct_parcel_count": distinct_parcels,
            "mutation_value": mutation_value,
            "mutation_date": mutation_date,
            "value_consistent": value_consistent,
            "geo_consistent": geo_consistent,
            "residential_property_type": rtype,
            "residential_surface": res_surface,
            "residential_rooms": res_rooms,
            "arrondissement": arrondissement,
            "longitude": lon,
            "latitude": lat,
            "source_year": int(rows["source_year"].iloc[0]),
            "source_file": rows["source_file"].iloc[0],
            "source_sha256": rows["source_sha256"].iloc[0],
        })

    return pd.DataFrame.from_records(records)


def add_price_eligibility(mutations: pd.DataFrame) -> pd.DataFrame:
    """Add is_price_per_m2_eligible, price_ineligibility_reason, price_per_m2_raw."""
    out = mutations.copy()

    def _reason(row: pd.Series) -> str | None:
        if row["residential_unit_count"] != 1:
            return "not_single_residential_unit"
        if not row["value_consistent"]:
            return "inconsistent_mutation_value"
        val = row["mutation_value"]
        if val is None or pd.isna(val) or val <= 0:
            return "missing_or_nonpositive_value"
        surf = row["residential_surface"]
        if surf is None or pd.isna(surf) or surf <= 0:
            return "missing_or_nonpositive_surface"
        if pd.isna(row["mutation_date"]):
            return "invalid_date"
        arr = row["arrondissement"]
        if arr is None or pd.isna(arr) or not (1 <= int(arr) <= 20):
            return "invalid_arrondissement"
        return None

    reasons = out.apply(_reason, axis=1)
    out["price_ineligibility_reason"] = reasons
    out["is_price_per_m2_eligible"] = reasons.isna()

    def _ppm2(row: pd.Series) -> float | None:
        if not row["is_price_per_m2_eligible"]:
            return None
        return float(row["mutation_value"]) / float(row["residential_surface"])

    out["price_per_m2_raw"] = out.apply(_ppm2, axis=1)
    return out


def price_distribution(mutations: pd.DataFrame) -> dict[str, Any]:
    """Return the full quantile distribution of eligible price_per_m2_raw."""
    eligible = mutations.loc[
        mutations["is_price_per_m2_eligible"], "price_per_m2_raw"
    ].dropna()
    if eligible.empty:
        return {"count": 0}
    q = {
        "min": float(eligible.min()),
        "p0_1": float(eligible.quantile(0.001)),
        "p0_5": float(eligible.quantile(0.005)),
        "p1": float(eligible.quantile(0.01)),
        "p5": float(eligible.quantile(0.05)),
        "p25": float(eligible.quantile(0.25)),
        "median": float(eligible.quantile(0.50)),
        "p75": float(eligible.quantile(0.75)),
        "p95": float(eligible.quantile(0.95)),
        "p99": float(eligible.quantile(0.99)),
        "p99_5": float(eligible.quantile(0.995)),
        "p99_9": float(eligible.quantile(0.999)),
        "max": float(eligible.max()),
    }
    q["count"] = int(eligible.shape[0])
    return q
