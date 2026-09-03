"""DVF quality metrics aggregation for the pipeline report.

Produces per-year and global counts consumed by the JSON quality report and its
human-readable Markdown summary. No address-level or individual-transaction
detail is emitted here -- only aggregates.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from real_estate_agent.processing.dvf.transformer import (
    REQUIRED_COLUMNS,
    SALE_NATURE,
    derive_arrondissement,
)

EXCLUDED_NATURES = (
    "Vente en l'état futur d'achèvement",
    "Échange",
    "Adjudication",
    "Vente terrain à bâtir",
)


def missing_required_counts(df: pd.DataFrame) -> dict[str, int]:
    """Count missing values in each required column that is present."""
    return {
        c: int(df[c].isna().sum())
        for c in REQUIRED_COLUMNS
        if c in df.columns
    }


def excluded_nature_counts(deduped: pd.DataFrame) -> dict[str, int]:
    """Count rows for each excluded mutation nature (reported, not kept in V1)."""
    counts: dict[str, int] = {}
    if "nature_mutation" not in deduped.columns:
        return counts
    vc = deduped["nature_mutation"].value_counts(dropna=False)
    for nature in EXCLUDED_NATURES:
        counts[nature] = int(vc.get(nature, 0))
    return counts


def invalid_paris_code_count(deduped: pd.DataFrame) -> int:
    """Count sale rows whose code_commune is not a valid Paris arrondissement."""
    sales = deduped.loc[deduped["nature_mutation"] == SALE_NATURE]
    if sales.empty:
        return 0
    arr = derive_arrondissement(sales["code_commune"])
    return int(arr.isna().sum())


def build_year_metrics(
    raw_rows: int,
    dedup_stats: dict[str, int],
    deduped: pd.DataFrame,
    components: pd.DataFrame,
    mutations: pd.DataFrame,
) -> dict[str, Any]:
    """Assemble the metrics dictionary for a single year."""
    unique_mutations = int(deduped["id_mutation"].nunique()) if not deduped.empty else 0
    residential_mutations = int(len(mutations))
    residential_units = int(len(components))

    n_mut = len(mutations)
    has_mut = not mutations.empty
    single_unit = int((mutations["residential_unit_count"] == 1).sum()) if has_mut else 0
    multi_unit = int((mutations["residential_unit_count"] > 1).sum()) if has_mut else 0
    apartments = int(mutations["apartment_count"].sum()) if has_mut else 0
    houses = int(mutations["house_count"].sum()) if has_mut else 0

    inconsistent_values = int((~mutations["value_consistent"]).sum()) if has_mut else 0
    ambiguous_geo = int((~mutations["geo_consistent"]).sum()) if has_mut else 0

    if has_mut:
        eligible = int(mutations["is_price_per_m2_eligible"].sum())
        eligibility_rate = round(eligible / n_mut * 100, 2)
    else:
        eligible = 0
        eligibility_rate = 0.0

    # Coordinate coverage on residential components.
    if not components.empty:
        coord_cov = round(
            components[["longitude", "latitude"]].notna().all(axis=1).mean() * 100, 2
        )
    else:
        coord_cov = 0.0

    # Invalid / missing surfaces among residential components.
    if not components.empty:
        surf = components["surface_reelle_bati"]
        invalid_surface = int((surf.isna() | (surf <= 0)).sum())
    else:
        invalid_surface = 0

    return {
        "raw_rows": int(raw_rows),
        "exact_duplicates": dedup_stats["exact_duplicates"],
        "deduplicated_rows": dedup_stats["rows_after_dedup"],
        "unique_mutations": unique_mutations,
        "residential_mutations": residential_mutations,
        "residential_units": residential_units,
        "single_unit_mutations": single_unit,
        "multi_unit_mutations": multi_unit,
        "apartment_count": apartments,
        "house_count": houses,
        "excluded_nature_counts": excluded_nature_counts(deduped),
        "missing_required": missing_required_counts(deduped),
        "invalid_paris_codes": invalid_paris_code_count(deduped),
        "inconsistent_mutation_values": inconsistent_values,
        "ambiguous_geography": ambiguous_geo,
        "invalid_or_missing_surfaces": invalid_surface,
        "price_eligible_count": eligible,
        "price_eligibility_rate_pct": eligibility_rate,
        "coordinate_coverage_pct": coord_cov,
    }
