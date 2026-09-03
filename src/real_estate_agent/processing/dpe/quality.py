"""DPE quality metrics aggregation for the pipeline report.

Aggregated statistics only -- no individual records, no textual addresses.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _quantiles(series: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {"count": 0}
    return {
        "min": float(s.min()),
        "p1": float(s.quantile(0.01)),
        "p5": float(s.quantile(0.05)),
        "p25": float(s.quantile(0.25)),
        "median": float(s.quantile(0.50)),
        "p75": float(s.quantile(0.75)),
        "p95": float(s.quantile(0.95)),
        "p99": float(s.quantile(0.99)),
        "max": float(s.max()),
        "count": int(s.shape[0]),
    }


def _counts(series: pd.Series) -> dict[str, int]:
    return {
        str(k): int(v)
        for k, v in series.value_counts(dropna=False).items()
    }


def build_report(
    df: pd.DataFrame,
    manifest: dict[str, Any],
    dedup_stats: dict[str, int],
    observed_types: dict[str, int],
) -> dict[str, Any]:
    """Assemble the full DPE quality report (aggregates only)."""
    label_eligible = df[df["is_label_analysis_eligible"]]
    intensity_eligible = df[df["is_intensity_analysis_eligible"]]

    # Population counts.
    pop_counts = _counts(df["analysis_population"])
    apartment_count = int((df["type_batiment_norm"] == "appartement").sum())
    house_count = int((df["type_batiment_norm"] == "maison").sum())
    whole_building_count = int((df["type_batiment_norm"] == "immeuble").sum())

    # Establishment-date range and per-year counts.
    est = pd.to_datetime(df["date_etablissement_dpe"], errors="coerce")
    year_counts = _counts(est.dt.year.astype("Int64"))
    date_min = str(est.min())
    date_max = str(est.max())

    complete_year_count = int(df["is_complete_analysis_year"].sum())
    partial_year_count = int(df["is_partial_year"].sum())

    # Arrondissement coverage (all 20).
    arr_counts_raw = df["arrondissement"].dropna().astype(int)
    arr_counts = {str(int(k)): int(v)
                  for k, v in arr_counts_raw.value_counts().sort_index().items()}
    covered = sorted(arr_counts_raw.unique().tolist())
    all_20 = set(range(1, 21))
    missing_arr = sorted(all_20 - set(covered))

    # INSEE/postal inconsistencies.
    inconsistencies = int((~df["is_geography_consistent"]).sum())

    # Missing-value rates on approved analytic fields.
    missing_pct = {
        c: round(df[c].isna().mean() * 100, 2)
        for c in ("numero_dpe", "date_etablissement_dpe", "etiquette_dpe",
                  "etiquette_ges", "surface_habitable_logement",
                  "conso_5_usages_par_m2_ep", "emission_ges_5_usages_par_m2",
                  "code_insee_ban", "_geopoint")
        if c in df.columns
    }

    coord_cov = round(df["_geopoint"].notna().mean() * 100, 2)

    return {
        "api_total_announced": manifest.get("expected_total"),
        "rows_retrieved": manifest.get("retrieved_rows"),
        "pagination_pages": manifest.get("page_count"),
        "extraction_started_utc": manifest.get("extraction_started_utc"),
        "extraction_finished_utc": manifest.get("extraction_finished_utc"),
        "exact_duplicates": dedup_stats["exact_duplicates"],
        "unique_numero_dpe": dedup_stats["unique_numero_dpe"],
        "missing_numero_dpe": dedup_stats["missing_numero_dpe"],
        "conflicting_duplicates": dedup_stats["conflicting_duplicates"],
        "processed_rows": int(len(df)),
        "label_analysis_eligible_rows": int(len(label_eligible)),
        "intensity_analysis_eligible_rows": int(len(intensity_eligible)),
        "analysis_population_counts": pop_counts,
        "apartment_count": apartment_count,
        "house_count": house_count,
        "whole_building_count": whole_building_count,
        "establishment_date_min": date_min,
        "establishment_date_max": date_max,
        "counts_by_year": year_counts,
        "complete_analysis_year_count_2021_2025": complete_year_count,
        "partial_year_count_2026": partial_year_count,
        "counts_by_arrondissement": arr_counts,
        "arrondissements_covered": len(covered),
        "arrondissements_missing": missing_arr,
        "insee_postal_inconsistencies": inconsistencies,
        "dpe_label_distribution": _counts(df["etiquette_dpe_norm"]),
        "ges_label_distribution": _counts(df["etiquette_ges_norm"]),
        "building_type_distribution_raw": observed_types,
        "building_type_distribution_norm": _counts(df["type_batiment_norm"]),
        "construction_period_distribution": _counts(df["periode_construction"]),
        "surface_quantiles": _quantiles(df["surface_habitable_logement"]),
        "consumption_quantiles": _quantiles(df["conso_5_usages_par_m2_ep"]),
        "emissions_quantiles": _quantiles(df["emission_ges_5_usages_par_m2"]),
        "missing_value_pct": missing_pct,
        "coordinate_coverage_pct": coord_cov,
        "label_exclusions_by_reason": _counts(df["label_exclusion_reason"]),
        "intensity_exclusions_by_reason": _counts(df["intensity_exclusion_reason"]),
        "outlier_policy": (
            "Original surface/consumption/emission values are preserved. Extreme "
            "values are reported but NOT excluded by arbitrary thresholds; they "
            "are not treated as invalid data. Robust statistics (medians) are "
            "preferred and sensitivity analysis is deferred to the Analytics phase."
        ),
    }