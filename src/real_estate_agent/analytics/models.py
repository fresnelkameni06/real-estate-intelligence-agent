"""Typed result models for the analytics engine.

Structured objects (not prose) suitable for FastAPI, Streamlit, AI tools and
tests. No addresses or individual transactions are ever included.
"""

from __future__ import annotations

from pydantic import BaseModel


class AppliedFilters(BaseModel):
    """Metadata describing the filters/policy applied to a result."""

    arrondissement: int | None = None
    start_year: int
    end_year: int
    price_per_m2_min: float
    price_per_m2_max: float
    includes_partial_year: bool = False
    eligibility_policy: str


class MarketOverview(BaseModel):
    """Market overview for an area (or all Paris) over a period."""

    total_residential_transactions: int
    price_eligible_transactions: int
    market_analysis_transactions: int
    excluded_outlier_count: int
    median_price_per_m2: float | None
    raw_eligible_median_price_per_m2: float | None
    sensitivity_median_difference: float | None
    median_residential_surface: float | None
    price_p25: float | None
    price_p75: float | None
    filters: AppliedFilters
    warnings: list[str] = []


class YearPricePoint(BaseModel):
    """One year of the price trend."""

    year: int
    transaction_count: int
    market_analysis_count: int
    median_price_per_m2: float | None
    price_p25: float | None
    price_p75: float | None
    yoy_median_change_pct: float | None


class PriceTrend(BaseModel):
    """Price trend across years."""

    points: list[YearPricePoint]
    filters: AppliedFilters
    warnings: list[str] = []


class AreaMarketMetrics(BaseModel):
    """Comparable market metrics for one arrondissement."""

    arrondissement: int
    total_residential_transactions: int
    market_analysis_transactions: int
    median_price_per_m2: float | None
    price_p25: float | None
    price_p75: float | None
    median_residential_surface: float | None


class ComparisonResult(BaseModel):
    """Comparison of several arrondissements over the same period/filters."""

    areas: list[AreaMarketMetrics]
    filters: AppliedFilters
    warnings: list[str] = []


class RankingEntry(BaseModel):
    """One arrondissement in a ranking, with its sample size."""

    arrondissement: int
    median_price_per_m2: float | None
    transaction_volume: int
    median_residential_surface: float | None
    sample_size: int
    sufficient_sample: bool


class AreaRankings(BaseModel):
    """Rankings of arrondissements by price, volume and surface."""

    by_median_price_per_m2: list[RankingEntry]
    by_transaction_volume: list[RankingEntry]
    by_median_surface: list[RankingEntry]
    min_sample_size: int
    filters: AppliedFilters
    warnings: list[str] = []


class DpeDistribution(BaseModel):
    """A-G label distribution for dwelling-unit DPE records."""

    eligible_dpe_count: int
    counts: dict[str, int]
    percentages: dict[str, float]
    f_count: int
    g_count: int
    fg_count: int
    fg_percentage: float
    start_year: int
    end_year: int
    includes_partial_year: bool
    warnings: list[str] = []


class DpeIntensitySummary(BaseModel):
    """Consumption/emission summary for intensity-eligible dwelling DPE."""

    eligible_intensity_count: int
    median_consumption: float | None
    consumption_p25: float | None
    consumption_p75: float | None
    median_emissions: float | None
    emissions_p25: float | None
    emissions_p75: float | None
    median_surface: float | None
    start_year: int
    end_year: int
    includes_partial_year: bool
    warnings: list[str] = []


class AreaProfile(BaseModel):
    """Combined market + DPE aggregates for one arrondissement.

    Combination happens only at the result level via a shared arrondissement and
    a compatible period. No record-level DVF/DPE join is performed.
    """

    arrondissement: int
    market: MarketOverview
    dpe_distribution: DpeDistribution
    dpe_intensity: DpeIntensitySummary
    warnings: list[str] = []
