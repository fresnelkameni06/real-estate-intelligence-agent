"""Parquet-to-database mapping helpers (pure, testable without a database).

Includes _geopoint parsing into (latitude, longitude), arrondissement casting
(float -> nullable int), and per-dataset column selection matching the models.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

# Columns loaded into dvf_mutations (must match the model).
DVF_DB_COLUMNS = [
    "id_mutation", "residential_unit_count", "apartment_count", "house_count",
    "dependency_count", "commercial_unit_count", "total_component_count",
    "distinct_parcel_count", "mutation_value", "mutation_date",
    "value_consistent", "geo_consistent", "residential_property_type",
    "residential_surface", "residential_rooms", "arrondissement",
    "longitude", "latitude", "source_year", "source_file", "source_sha256",
    "is_price_per_m2_eligible", "price_ineligibility_reason", "price_per_m2_raw",
]

# Columns loaded into dpe_diagnostics (must match the model).
DPE_DB_COLUMNS = [
    "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe",
    "diagnostic_year", "etiquette_dpe_norm", "etiquette_ges_norm",
    "surface_habitable_logement", "conso_5_usages_par_m2_ep",
    "emission_ges_5_usages_par_m2", "type_batiment_norm", "analysis_population",
    "periode_construction", "arrondissement", "latitude", "longitude",
    "is_valid_arrondissement", "is_geography_consistent", "is_valid_dpe_label",
    "is_valid_ges_label", "is_valid_surface", "is_valid_consumption",
    "is_valid_emission", "is_residential_unit_type",
    "is_label_analysis_eligible", "is_intensity_analysis_eligible",
    "is_complete_analysis_year", "is_partial_year",
    "label_exclusion_reason", "intensity_exclusion_reason",
]

# Address-level columns that must NEVER appear in a loaded frame.
FORBIDDEN_ADDRESS_COLUMNS = {
    "adresse_ban", "adresse_brut", "adresse_nom_voie", "adresse_numero",
    "nom_rue_ban", "numero_rue_ban", "adresse_code_voie",
}


def parse_geopoint(value: Any) -> tuple[float | None, float | None]:
    """Parse a DataFair ``_geopoint`` "lat,lon" string into (lat, lon).

    Malformed values return (None, None) rather than raising, so one bad row
    cannot crash a whole load. Coordinates outside valid ranges become None.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None, None
    if not isinstance(value, str):
        return None, None
    parts = value.split(",")
    if len(parts) != 2:
        return None, None
    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
    except (ValueError, TypeError):
        return None, None
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, None
    return lat, lon


def _cast_arrondissement(series: pd.Series) -> pd.Series:
    """Cast a float/int arrondissement column to a nullable Int (NaN -> NA)."""
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _dates_to_date(series: pd.Series) -> pd.Series:
    """Convert a datetime column to python date objects (NaT -> None)."""
    dt = pd.to_datetime(series, errors="coerce")
    return dt.dt.date.where(dt.notna(), other=None)


def prepare_dvf_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DVF frame with exactly the DB columns and correct types."""
    out = df.copy()
    if "arrondissement" in out.columns:
        out["arrondissement"] = _cast_arrondissement(out["arrondissement"])
    if "mutation_date" in out.columns:
        out["mutation_date"] = _dates_to_date(out["mutation_date"])
    missing = [c for c in DVF_DB_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"DVF frame missing required columns: {missing}")
    return out[DVF_DB_COLUMNS]


def prepare_dpe_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DPE frame with DB columns, parsed coordinates, correct types."""
    out = df.copy()

    # Parse _geopoint -> latitude/longitude if not already present as columns.
    if "_geopoint" in out.columns:
        coords = out["_geopoint"].map(parse_geopoint)
        out["latitude"] = [c[0] for c in coords]
        out["longitude"] = [c[1] for c in coords]

    if "arrondissement" in out.columns:
        out["arrondissement"] = _cast_arrondissement(out["arrondissement"])
    for c in ("date_etablissement_dpe", "date_fin_validite_dpe"):
        if c in out.columns:
            out[c] = _dates_to_date(out[c])

    # Guard: no forbidden address columns.
    present_forbidden = FORBIDDEN_ADDRESS_COLUMNS & set(out.columns)
    if present_forbidden:
        raise ValueError(f"Address-level columns must not be loaded: {present_forbidden}")

    missing = [c for c in DPE_DB_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"DPE frame missing required columns: {missing}")
    return out[DPE_DB_COLUMNS]
