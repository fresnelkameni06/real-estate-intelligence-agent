"""Deterministic DPE transformations for the Paris diagnostics dataset.

Pipeline:

    load snapshot -> validate schema -> typed parsing (dates, numerics)
        -> exact-duplicate detection -> numero_dpe duplicate/conflict resolution
        -> arrondissement derivation (INSEE primary, postal fallback)
        -> DPE/GES label normalization -> building-type normalization
        -> quality flags + exclusion reasons

Domain notes:

* a DPE is a diagnostic, not a dwelling; the same dwelling can have several DPEs;
* the dataset represents available diagnostics, NOT the full Paris housing stock;
* geography uses ``code_insee_ban`` (75101-75120) as primary; ``code_postal_ban``
  (75001-75020) is only a documented fallback when INSEE is missing.

Building-type category values are NOT assumed. ``observed_building_types`` returns
the real categories so they can be reported before mapping; the normalization
maps known ADEME forms and flags anything unexpected.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

APPROVED_FIELDS = [
    "_id", "numero_dpe", "date_etablissement_dpe", "date_reception_dpe",
    "date_fin_validite_dpe", "etiquette_dpe", "etiquette_ges",
    "conso_5_usages_par_m2_ep", "emission_ges_5_usages_par_m2",
    "surface_habitable_logement", "type_batiment", "periode_construction",
    "code_postal_ban", "code_insee_ban", "code_departement_ban", "_geopoint",
]

REQUIRED_FIELDS = [
    "numero_dpe", "date_etablissement_dpe", "etiquette_dpe", "etiquette_ges",
    "code_insee_ban", "surface_habitable_logement",
]

STRING_FIELDS = [
    "_id", "numero_dpe", "etiquette_dpe", "etiquette_ges", "type_batiment",
    "periode_construction", "code_postal_ban", "code_insee_ban",
    "code_departement_ban", "_geopoint",
]

NUMERIC_FIELDS = [
    "conso_5_usages_par_m2_ep", "emission_ges_5_usages_par_m2",
    "surface_habitable_logement",
]

DATE_FIELDS = [
    "date_etablissement_dpe", "date_reception_dpe", "date_fin_validite_dpe",
]

VALID_LABELS = {"A", "B", "C", "D", "E", "F", "G"}

# Documented building-type mapping. Values are normalized to a small set; any
# value not seen here is flagged (see observed_building_types + normalize).
# Residential unit types for analysis eligibility are "maison" and "appartement".
BUILDING_TYPE_MAP = {
    "maison": "maison",
    "appartement": "appartement",
    "immeuble": "immeuble",
}
RESIDENTIAL_UNIT_TYPES = {"maison", "appartement"}

# Analysis population derived from the normalized building type:
#   dwelling_unit  -> appartement, maison (a single dwelling)
#   whole_building -> immeuble (a whole-building diagnostic)
#   unknown        -> unexpected / unmapped values
ANALYSIS_POPULATION_MAP = {
    "appartement": "dwelling_unit",
    "maison": "dwelling_unit",
    "immeuble": "whole_building",
}

# Complete common analysis years for the project. 2026 is retained but partial.
COMPLETE_ANALYSIS_YEARS = {2021, 2022, 2023, 2024, 2025}
PARTIAL_YEARS = {2026}


class DPESchemaError(RuntimeError):
    """Raised when required DPE columns are missing."""


def _id_to_str(series: pd.Series) -> pd.Series:
    out = series.astype("string")
    mask = out.notna()
    out.loc[mask] = out.loc[mask].str.replace(r"\.0$", "", regex=True)
    return out


def load_snapshot_frame(results: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a typed DataFrame from snapshot ``results``."""
    df = pd.DataFrame(results)
    # Ensure all approved columns exist (missing -> NA column), no invention.
    for col in APPROVED_FIELDS:
        if col not in df.columns:
            df[col] = pd.NA
    for col in STRING_FIELDS:
        df[col] = _id_to_str(df[col])
    for col in NUMERIC_FIELDS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in DATE_FIELDS:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def validate_schema(df: pd.DataFrame) -> None:
    """Raise DPESchemaError if any required column is missing."""
    missing = [c for c in REQUIRED_FIELDS if c not in df.columns]
    if missing:
        raise DPESchemaError(f"Missing required DPE columns: {missing}")


def observed_building_types(df: pd.DataFrame) -> dict[str, int]:
    """Return the real distribution of type_batiment for reporting."""
    if "type_batiment" not in df.columns:
        return {}
    return {
        str(k): int(v)
        for k, v in df["type_batiment"].value_counts(dropna=False).items()
    }


def normalize_label(series: pd.Series) -> pd.Series:
    """Uppercase/trim a DPE or GES label; invalid values become <NA>."""
    norm = series.astype("string").str.strip().str.upper()
    return norm.where(norm.isin(VALID_LABELS), other=pd.NA)


def normalize_building_type(series: pd.Series) -> pd.Series:
    """Map building type to a documented normalized value; unknowns -> <NA>."""
    lowered = series.astype("string").str.strip().str.lower()
    return lowered.map(BUILDING_TYPE_MAP).astype("string")


def derive_arrondissement(
    code_insee: pd.Series, code_postal: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """Derive arrondissement (1-20) from INSEE primary, postal fallback.

    Returns (arrondissement Int64, source label: 'insee'|'postal'|<NA>).
    """
    insee_map = {f"751{n:02d}": n for n in range(1, 21)}
    postal_map = {f"750{n:02d}": n for n in range(1, 21)}

    arr = code_insee.map(insee_map).astype("Int64")
    source = pd.Series(pd.NA, index=code_insee.index, dtype="string")
    source[arr.notna()] = "insee"

    # Fallback to postal only where INSEE gave nothing.
    need = arr.isna()
    postal_arr = code_postal.map(postal_map).astype("Int64")
    arr[need] = postal_arr[need]
    source[need & postal_arr.notna()] = "postal"
    return arr, source


def geography_consistent(
    code_insee: pd.Series, code_postal: pd.Series
) -> pd.Series:
    """Flag rows where INSEE and postal arrondissements disagree.

    True when both are present and map to the same arrondissement, or when one
    is missing (nothing to contradict). False only on an actual disagreement.
    """
    insee_map = {f"751{n:02d}": n for n in range(1, 21)}
    postal_map = {f"750{n:02d}": n for n in range(1, 21)}
    insee_arr = code_insee.map(insee_map)
    postal_arr = code_postal.map(postal_map)
    both = insee_arr.notna() & postal_arr.notna()
    disagree = both & (insee_arr != postal_arr)
    return ~disagree


def resolve_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Deterministically keep one row per numero_dpe.

    Strategy: drop exact-duplicate rows first, then for remaining duplicate
    numero_dpe keep the row with the most recent date_etablissement_dpe, breaking
    ties by _id (stable, deterministic). Rows with missing numero_dpe are kept
    as-is (they cannot be de-duplicated by key) and counted separately.
    """
    before = int(len(df))
    exact_dups = int(df.duplicated().sum())
    df = df.drop_duplicates().copy()

    missing_key = int(df["numero_dpe"].isna().sum())

    # Conflicting duplicates: same numero_dpe, differing on any other field.
    dup_mask = df["numero_dpe"].notna() & df["numero_dpe"].duplicated(keep=False)
    dup_groups = df.loc[dup_mask]
    conflicting = 0
    if not dup_groups.empty:
        for _, grp in dup_groups.groupby("numero_dpe"):
            if len(grp.drop_duplicates()) > 1:
                conflicting += 1

    # Deterministic resolution: newest establishment date, then _id.
    keyed = df[df["numero_dpe"].notna()].copy()
    keyed["_sort_date"] = keyed["date_etablissement_dpe"].fillna(pd.Timestamp.min)
    keyed = keyed.sort_values(
        ["numero_dpe", "_sort_date", "_id"], ascending=[True, False, True]
    )
    resolved = keyed.drop_duplicates(subset="numero_dpe", keep="first")
    resolved = resolved.drop(columns=["_sort_date"])

    unkeyed = df[df["numero_dpe"].isna()]
    out = pd.concat([resolved, unkeyed], ignore_index=True)

    stats = {
        "rows_before": before,
        "exact_duplicates": exact_dups,
        "missing_numero_dpe": missing_key,
        "conflicting_duplicates": conflicting,
        "unique_numero_dpe": int(resolved["numero_dpe"].nunique()),
        "rows_after": int(len(out)),
    }
    return out, stats


def add_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Add validity flags, analysis eligibility, and exclusion reason."""
    out = df.copy()

    arr, arr_source = derive_arrondissement(out["code_insee_ban"], out["code_postal_ban"])
    out["arrondissement"] = arr
    out["arrondissement_source"] = arr_source

    out["etiquette_dpe_norm"] = normalize_label(out["etiquette_dpe"])
    out["etiquette_ges_norm"] = normalize_label(out["etiquette_ges"])
    out["type_batiment_norm"] = normalize_building_type(out["type_batiment"])

    out["is_valid_dpe_number"] = out["numero_dpe"].notna()
    out["is_valid_arrondissement"] = out["arrondissement"].notna()
    out["is_geography_consistent"] = geography_consistent(
        out["code_insee_ban"], out["code_postal_ban"]
    )
    out["is_valid_dpe_label"] = out["etiquette_dpe_norm"].notna()
    out["is_valid_ges_label"] = out["etiquette_ges_norm"].notna()
    surf = out["surface_habitable_logement"]
    out["is_valid_surface"] = surf.notna() & (surf > 0)
    conso = out["conso_5_usages_par_m2_ep"]
    out["is_valid_consumption"] = conso.notna() & (conso >= 0)
    emis = out["emission_ges_5_usages_par_m2"]
    out["is_valid_emission"] = emis.notna() & (emis >= 0)
    out["is_residential_unit_type"] = out["type_batiment_norm"].isin(
        RESIDENTIAL_UNIT_TYPES
    )

    # Analysis population: dwelling_unit / whole_building / unknown.
    # A whole-building (immeuble) diagnostic must not be mixed with dwelling-level
    # analytics, so it is a distinct population rather than an exclusion.
    out["analysis_population"] = (
        out["type_batiment_norm"].map(ANALYSIS_POPULATION_MAP).astype("string")
    )
    out["analysis_population"] = out["analysis_population"].fillna("unknown")

    # Partial-year handling: 2021-2025 complete, 2026 partial, retained.
    est = pd.to_datetime(out["date_etablissement_dpe"], errors="coerce")
    out["diagnostic_year"] = est.dt.year.astype("Int64")
    out["is_complete_analysis_year"] = out["diagnostic_year"].isin(
        COMPLETE_ANALYSIS_YEARS
    )
    out["is_partial_year"] = out["diagnostic_year"].isin(PARTIAL_YEARS)

    is_dwelling = out["analysis_population"] == "dwelling_unit"

    # --- Label-analysis eligibility (surface NOT required) ---
    def _label_reason(row: pd.Series) -> str | None:
        if not row["is_valid_dpe_number"]:
            return "missing_numero_dpe"
        if not row["is_valid_arrondissement"]:
            return "invalid_arrondissement"
        if not row["is_valid_dpe_label"]:
            return "invalid_dpe_label"
        if row["analysis_population"] != "dwelling_unit":
            return "not_dwelling_unit"
        return None

    label_reasons = out.apply(_label_reason, axis=1)
    out["label_exclusion_reason"] = label_reasons
    out["is_label_analysis_eligible"] = label_reasons.isna()

    # --- Intensity-analysis eligibility (surface + conso + emission required) ---
    def _intensity_reason(row: pd.Series) -> str | None:
        base = row["label_exclusion_reason"]
        if base is not None:
            return base
        if not row["is_valid_surface"]:
            return "invalid_surface"
        if not row["is_valid_consumption"]:
            return "invalid_consumption"
        if not row["is_valid_emission"]:
            return "invalid_emission"
        return None

    intensity_reasons = out.apply(_intensity_reason, axis=1)
    out["intensity_exclusion_reason"] = intensity_reasons
    out["is_intensity_analysis_eligible"] = intensity_reasons.isna()

    # Backward-compatibility alias (documented). No downstream consumers yet;
    # kept only so older references do not break. Prefer the explicit flags above.
    out["is_analysis_eligible"] = out["is_intensity_analysis_eligible"]
    out["exclusion_reason"] = out["intensity_exclusion_reason"]
    # silence unused-variable lint while keeping the semantic marker explicit
    _ = is_dwelling
    return out


PROCESSED_COLUMNS = [
    "numero_dpe", "date_etablissement_dpe", "date_reception_dpe",
    "date_fin_validite_dpe", "diagnostic_year",
    "etiquette_dpe", "etiquette_dpe_norm", "etiquette_ges", "etiquette_ges_norm",
    "conso_5_usages_par_m2_ep", "emission_ges_5_usages_par_m2",
    "surface_habitable_logement", "type_batiment", "type_batiment_norm",
    "analysis_population",
    "periode_construction", "code_insee_ban", "code_postal_ban",
    "arrondissement", "arrondissement_source", "_geopoint",
    "is_valid_dpe_number", "is_valid_arrondissement", "is_geography_consistent",
    "is_valid_dpe_label", "is_valid_ges_label", "is_valid_surface",
    "is_valid_consumption", "is_valid_emission", "is_residential_unit_type",
    "is_complete_analysis_year", "is_partial_year",
    "is_label_analysis_eligible", "label_exclusion_reason",
    "is_intensity_analysis_eligible", "intensity_exclusion_reason",
    "is_analysis_eligible", "exclusion_reason",
]


def select_processed_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the processed columns (no full textual address present)."""
    cols = [c for c in PROCESSED_COLUMNS if c in df.columns]
    return df[cols].reset_index(drop=True)