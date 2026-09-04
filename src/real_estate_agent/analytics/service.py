"""Analytics service: business calculations and result composition.

Wraps the repository queries, applies rounding and policy, computes derived
values (YoY, sensitivity, percentages), and returns typed result models. Handles
empty sets, NULLs, division by zero, and missing baselines.
"""

from __future__ import annotations

from sqlalchemy import Engine

from real_estate_agent.analytics import policy, repository, validators
from real_estate_agent.analytics.models import (
    AppliedFilters,
    AreaMarketMetrics,
    AreaProfile,
    AreaRankings,
    ComparisonResult,
    DpeDistribution,
    DpeIntensitySummary,
    MarketOverview,
    PriceTrend,
    RankingEntry,
    YearPricePoint,
)

_ELIGIBILITY_POLICY = (
    "market: is_price_per_m2_eligible AND "
    f"{policy.PRICE_PER_M2_MIN} <= price_per_m2_raw <= {policy.PRICE_PER_M2_MAX}; "
    "dpe labels: is_label_analysis_eligible AND dwelling_unit; "
    "dpe intensity: is_intensity_analysis_eligible AND dwelling_unit"
)


def _r(value: float | None, decimals: int) -> float | None:
    """Round a nullable float, preserving None."""
    return None if value is None else round(float(value), decimals)


def _filters(
    arr: int | None, start_year: int, end_year: int
) -> AppliedFilters:
    return AppliedFilters(
        arrondissement=arr,
        start_year=start_year,
        end_year=end_year,
        price_per_m2_min=policy.PRICE_PER_M2_MIN,
        price_per_m2_max=policy.PRICE_PER_M2_MAX,
        includes_partial_year=validators.includes_partial_year(start_year, end_year),
        eligibility_policy=_ELIGIBILITY_POLICY,
    )


def get_market_overview(
    engine: Engine,
    arrondissement: int | None = None,
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> MarketOverview:
    """Market overview for an area/period."""
    arrondissement = validators.validate_arrondissement(arrondissement)
    start_year, end_year = validators.validate_year_range(start_year, end_year)

    row = repository.market_overview_row(engine, arrondissement, start_year, end_year)
    total = int(row.get("total_tx") or 0)
    eligible = int(row.get("eligible_tx") or 0)
    market = int(row.get("market_tx") or 0)
    raw_median = _r(row.get("raw_median"), policy.ROUND_PRICE)
    market_median = _r(row.get("market_median"), policy.ROUND_PRICE)

    sensitivity = None
    if raw_median is not None and market_median is not None:
        sensitivity = round(market_median - raw_median, policy.ROUND_PRICE)

    warnings: list[str] = []
    if total == 0:
        warnings.append("No residential transactions for the requested scope.")
    if market == 0 and eligible > 0:
        warnings.append("All eligible transactions fell outside plausibility band.")

    return MarketOverview(
        total_residential_transactions=total,
        price_eligible_transactions=eligible,
        market_analysis_transactions=market,
        excluded_outlier_count=eligible - market,
        median_price_per_m2=market_median,
        raw_eligible_median_price_per_m2=raw_median,
        sensitivity_median_difference=sensitivity,
        median_residential_surface=_r(row.get("median_surface"), policy.ROUND_SURFACE),
        price_p25=_r(row.get("price_p25"), policy.ROUND_PRICE),
        price_p75=_r(row.get("price_p75"), policy.ROUND_PRICE),
        filters=_filters(arrondissement, start_year, end_year),
        warnings=warnings,
    )


def get_price_trend(
    engine: Engine,
    arrondissement: int | None = None,
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> PriceTrend:
    """Yearly price trend with YoY median change."""
    arrondissement = validators.validate_arrondissement(arrondissement)
    start_year, end_year = validators.validate_year_range(start_year, end_year)

    rows = repository.price_trend_rows(engine, arrondissement, start_year, end_year)
    by_year = {int(r["year"]): r for r in rows}

    points: list[YearPricePoint] = []
    for year in range(start_year, end_year + 1):
        r = by_year.get(year)
        median = _r(r["median_price"], policy.ROUND_PRICE) if r else None
        prev = by_year.get(year - 1)
        prev_median = prev["median_price"] if prev else None
        # YoY is NULL when there is no valid previous-year baseline (> 0).
        yoy = None
        if median is not None and prev_median not in (None, 0):
            yoy = round((median - float(prev_median)) / float(prev_median) * 100,
                        policy.ROUND_PCT)
        points.append(YearPricePoint(
            year=year,
            transaction_count=int(r["tx_count"]) if r else 0,
            market_analysis_count=int(r["market_count"]) if r else 0,
            median_price_per_m2=median,
            price_p25=_r(r["p25"], policy.ROUND_PRICE) if r else None,
            price_p75=_r(r["p75"], policy.ROUND_PRICE) if r else None,
            yoy_median_change_pct=yoy,
        ))

    return PriceTrend(points=points,
                      filters=_filters(arrondissement, start_year, end_year))


def compare_arrondissements(
    engine: Engine,
    arrondissements: list[int],
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> ComparisonResult:
    """Compare 2-20 arrondissements over the same period/filters."""
    areas = validators.validate_comparison_areas(arrondissements)
    start_year, end_year = validators.validate_year_range(start_year, end_year)

    rows = repository.area_metrics_rows(engine, areas, start_year, end_year)
    by_arr = {int(r["arrondissement"]): r for r in rows}

    metrics: list[AreaMarketMetrics] = []
    for a in areas:
        r = by_arr.get(a)
        metrics.append(AreaMarketMetrics(
            arrondissement=a,
            total_residential_transactions=int(r["total_tx"]) if r else 0,
            market_analysis_transactions=int(r["market_tx"]) if r else 0,
            median_price_per_m2=_r(r["median_price"], policy.ROUND_PRICE) if r else None,
            price_p25=_r(r["p25"], policy.ROUND_PRICE) if r else None,
            price_p75=_r(r["p75"], policy.ROUND_PRICE) if r else None,
            median_residential_surface=(
                _r(r["median_surface"], policy.ROUND_SURFACE) if r else None
            ),
        ))
    # filters.arrondissement is None because several areas are compared.
    return ComparisonResult(areas=metrics,
                            filters=_filters(None, start_year, end_year))


def get_area_rankings(
    engine: Engine,
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> AreaRankings:
    """Rank arrondissements by price, volume and surface (with sample sizes)."""
    start_year, end_year = validators.validate_year_range(start_year, end_year)
    rows = repository.ranking_rows(engine, start_year, end_year)

    entries: list[RankingEntry] = []
    for r in rows:
        sample = int(r["market_count"] or 0)
        entries.append(RankingEntry(
            arrondissement=int(r["arrondissement"]),
            median_price_per_m2=_r(r["median_price"], policy.ROUND_PRICE),
            transaction_volume=sample,
            median_residential_surface=_r(r["median_surface"], policy.ROUND_SURFACE),
            sample_size=sample,
            sufficient_sample=sample >= policy.MIN_RANKING_SAMPLE,
        ))

    sufficient = [e for e in entries if e.sufficient_sample]

    by_price = sorted(
        [e for e in sufficient if e.median_price_per_m2 is not None],
        key=lambda e: e.median_price_per_m2, reverse=True,
    )
    by_volume = sorted(sufficient, key=lambda e: e.transaction_volume, reverse=True)
    by_surface = sorted(
        [e for e in sufficient if e.median_residential_surface is not None],
        key=lambda e: e.median_residential_surface, reverse=True,
    )

    warnings: list[str] = []
    insufficient = [e.arrondissement for e in entries if not e.sufficient_sample]
    if insufficient:
        warnings.append(
            f"Arrondissements with sample < {policy.MIN_RANKING_SAMPLE} excluded "
            f"from rankings: {insufficient}"
        )

    return AreaRankings(
        by_median_price_per_m2=by_price,
        by_transaction_volume=by_volume,
        by_median_surface=by_surface,
        min_sample_size=policy.MIN_RANKING_SAMPLE,
        filters=_filters(None, start_year, end_year),
        warnings=warnings,
    )


def get_dpe_distribution(
    engine: Engine,
    arrondissement: int | None = None,
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> DpeDistribution:
    """A-G distribution for dwelling-unit, label-eligible DPE."""
    arrondissement = validators.validate_arrondissement(arrondissement)
    start_year, end_year = validators.validate_year_range(start_year, end_year)

    counts_raw = repository.dpe_distribution_row(
        engine, arrondissement, start_year, end_year
    )
    counts = {label: int(counts_raw.get(label, 0)) for label in policy.VALID_LABELS}
    total = sum(counts.values())

    percentages = {
        label: (round(counts[label] / total * 100, policy.ROUND_PCT) if total else 0.0)
        for label in policy.VALID_LABELS
    }
    f_count = counts["F"]
    g_count = counts["G"]
    fg = f_count + g_count
    fg_pct = round(fg / total * 100, policy.ROUND_PCT) if total else 0.0

    warnings: list[str] = []
    if total == 0:
        warnings.append("No label-eligible dwelling-unit DPE for the requested scope.")

    return DpeDistribution(
        eligible_dpe_count=total,
        counts=counts,
        percentages=percentages,
        f_count=f_count,
        g_count=g_count,
        fg_count=fg,
        fg_percentage=fg_pct,
        start_year=start_year,
        end_year=end_year,
        includes_partial_year=validators.includes_partial_year(start_year, end_year),
        warnings=warnings,
    )


def get_dpe_intensity_summary(
    engine: Engine,
    arrondissement: int | None = None,
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> DpeIntensitySummary:
    """Consumption/emission summary for intensity-eligible dwelling DPE."""
    arrondissement = validators.validate_arrondissement(arrondissement)
    start_year, end_year = validators.validate_year_range(start_year, end_year)

    row = repository.dpe_intensity_row(engine, arrondissement, start_year, end_year)
    n = int(row.get("n") or 0)
    warnings: list[str] = []
    if n == 0:
        warnings.append("No intensity-eligible dwelling-unit DPE for the scope.")

    return DpeIntensitySummary(
        eligible_intensity_count=n,
        median_consumption=_r(row.get("med_conso"), policy.ROUND_INTENSITY),
        consumption_p25=_r(row.get("conso_p25"), policy.ROUND_INTENSITY),
        consumption_p75=_r(row.get("conso_p75"), policy.ROUND_INTENSITY),
        median_emissions=_r(row.get("med_emis"), policy.ROUND_INTENSITY),
        emissions_p25=_r(row.get("emis_p25"), policy.ROUND_INTENSITY),
        emissions_p75=_r(row.get("emis_p75"), policy.ROUND_INTENSITY),
        median_surface=_r(row.get("med_surface"), policy.ROUND_SURFACE),
        start_year=start_year,
        end_year=end_year,
        includes_partial_year=validators.includes_partial_year(start_year, end_year),
        warnings=warnings,
    )


def get_area_profile(
    engine: Engine,
    arrondissement: int,
    start_year: int = policy.DEFAULT_START_YEAR,
    end_year: int = policy.DEFAULT_END_YEAR,
) -> AreaProfile:
    """Combine market + DPE aggregates for one arrondissement.

    Combination happens only here, at the result level, via a shared
    arrondissement and compatible period. No record-level DVF/DPE join.
    """
    arr = validators.validate_arrondissement(arrondissement)
    if arr is None:
        from real_estate_agent.analytics.validators import AnalyticsInputError
        raise AnalyticsInputError("get_area_profile requires an arrondissement (1-20)")

    market = get_market_overview(engine, arr, start_year, end_year)
    dpe_dist = get_dpe_distribution(engine, arr, start_year, end_year)
    dpe_int = get_dpe_intensity_summary(engine, arr, start_year, end_year)

    return AreaProfile(
        arrondissement=arr,
        market=market,
        dpe_distribution=dpe_dist,
        dpe_intensity=dpe_int,
    )
