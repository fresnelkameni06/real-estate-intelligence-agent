# Analytics Engine — Phase 4

Deterministic market and DPE analytics computed in PostgreSQL. The LLM never
calculates KPIs; it may only interpret these structured results later.

## Business definitions

- **Residential mutation**: one DVF sale of an apartment/house (mutation grain).
- **Price per m² (raw)**: `mutation_value / residential_surface` for a
  single-unit residential sale (computed in Phase 2, stored per mutation).
- **Market median price/m²**: the median over plausibility-filtered eligible
  mutations — the headline market indicator.
- **DPE label**: energy class A–G for a dwelling-unit diagnostic.
- **Intensity**: energy consumption (kWh/m²/yr) and GES emissions (kgCO₂/m²/yr).

## Period policy

Default complete analytical period: **2021–2025**. **2026 is partial** and is
excluded by default; it remains available for DPE if a caller explicitly requests
a range including 2026 (`includes_partial_year` is then set on the result). DVF
holds no 2026 data (the `source_year` CHECK is 2021–2025).

## Eligibility rules

- **Market price stats**: `is_price_per_m2_eligible = true` AND
  `1000 <= price_per_m2_raw <= 50000`.
- **DPE labels**: `is_label_analysis_eligible = true` AND
  `analysis_population = 'dwelling_unit'`.
- **DPE intensity**: `is_intensity_analysis_eligible = true` AND
  `analysis_population = 'dwelling_unit'`.

Whole-building (`immeuble`) DPE records are never mixed into dwelling-unit
analytics.

## Price plausibility policy

The band `[1000, 50000] €/m²` is a broad, configurable analytical limit (in
`policy.py`). Records outside it are **excluded from the market median but never
deleted**. Every market result reports both the **raw eligible median** and the
**plausibility-filtered market median**, plus their **sensitivity difference**,
so the effect of filtering is always visible. The full outlier evidence was
provided in Phase 2; this band is the agreed analytical treatment, not a data
deletion.

## Formulas

- **Median / quartiles**: PostgreSQL `percentile_cont(0.5 | 0.25 | 0.75)
  WITHIN GROUP (ORDER BY …)`.
- **YoY median change**: `(median_year − median_prev) / median_prev × 100`;
  **NULL** when there is no valid previous-year baseline (missing or zero).
- **F+G share**: `(F + G) / total_label_eligible × 100`.
- **Excluded outliers**: `price_eligible − market_analysis`.

## SQL aggregation approach

All aggregates run in the database over the fact tables; the million-row tables
are **never** loaded into Pandas. Counts and both medians (raw and filtered) are
produced in a single pass using `FILTER (WHERE …)` clauses. Every query is
parameterized (bound parameters, `IN` via an expanding bindparam); no SQL is
built by concatenating user input.

## Rounding rules

Prices, percentages, surfaces, consumption and emissions are all rounded to
**2 decimals**. Rounding is applied at the service layer, preserving `None` for
absent values.

## Capabilities

- `get_market_overview(arr?, start, end)`
- `get_price_trend(arr?, start, end)` — per-year, with YoY
- `compare_arrondissements([2..20 unique], start, end)`
- `get_area_rankings(start, end)` — by price, volume, surface, with sample sizes
- `get_dpe_distribution(arr?, start, end)` — A–G counts/percentages, F+G
- `get_dpe_intensity_summary(arr?, start, end)`
- `get_area_profile(arr, start, end)` — market + DPE combined at the result
  level via a shared arrondissement and compatible period (no record-level
  DVF/DPE join)

## Minimum sample size

Ranking entries require at least **30** plausibility-filtered mutations
(`MIN_RANKING_SAMPLE`). Arrondissements below that are reported as insufficient
sample and excluded from the rankings (listed in `warnings`), to avoid ranking
on a noisy median.

## Result models

All capabilities return typed Pydantic models carrying metadata (applied
filters, period, sample sizes, eligibility policy, partial-year inclusion,
warnings). No addresses or individual transactions are included, so the results
are safe for FastAPI, Streamlit, AI tools and tests.

## Error handling

Empty result sets, NULLs, division by zero, missing previous years, invalid
years, invalid arrondissements and duplicate arrondissement inputs are all
handled explicitly (validators raise clear `AnalyticsInputError`; derived values
degrade to `None` rather than crashing).

## Limitations

- DVF and DPE are compared only at arrondissement + period aggregate level; no
  property-level relationship is asserted.
- The plausibility band is deliberate and configurable; changing it changes the
  market median (the raw median is always reported alongside for transparency).
- 2026 DPE is partial; totals including it are not comparable to complete years.
