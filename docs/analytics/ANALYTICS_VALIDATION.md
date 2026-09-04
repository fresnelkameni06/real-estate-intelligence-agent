# Analytics Validation — Phase 4

> Real-data validation of the analytics engine against the development database
> (`real_estate_db`, PostgreSQL 18.6), executed 2026-09-04.
> Aggregate results only — no addresses, no individual transactions.
> Reproduce with `py scripts/run_analytics_validation.py`.

## Invariants — all passed ✅

| Invariant | Result |
|---|---|
| market ≤ price-eligible ≤ total | ✅ true |
| all arrondissements in 1–20 | ✅ true |
| F+G count ≤ eligible DPE count | ✅ true |
| A–G percentages sum ≈ 100 | ✅ true |
| default excludes partial 2026 | ✅ true |

`all_invariants_passed: true`

## A. Paris market overview 2021–2025

| Metric | Value |
|---|---|
| Total residential transactions | **160 977** |
| Price-eligible transactions | 152 578 |
| Market-analysis transactions | 148 254 |
| Excluded outliers | 4 324 |
| **Median price/m² (filtered)** | **10 348.84 €** |
| Raw eligible median | 10 271.17 € |
| Sensitivity difference | +77.67 € |
| Median residential surface | 43.0 m² |
| Price P25 / P75 | 8 750.00 / 12 147.02 € |

The small sensitivity (+77.67 €) shows the plausibility band removes extreme
outliers without distorting the central tendency — the market median stays close
to the raw median.

## B. Annual price trend (Paris)

| Year | Median €/m² | Market n | YoY |
|---|---|---|---|
| 2021 | 10 909.09 | 31 530 | — (no baseline) |
| 2022 | 10 781.25 | 34 301 | −1.17 % |
| 2023 | 10 230.77 | 27 827 | −5.11 % |
| 2024 | 9 642.86 | 25 302 | −5.75 % |
| 2025 | 9 763.48 | 29 294 | +1.25 % |

A clear cooling of the Paris market 2022–2024, with a slight rebound in 2025 —
consistent with known market dynamics. YoY is correctly NULL for 2021.

## C. Comparison — 13th vs 20th arrondissement

| Arr | Median €/m² | Market tx | Median surface |
|---|---|---|---|
| 13 | 9 200.00 | 7 374 | 40.0 m² |
| 20 | 8 896.92 | 9 943 | 40.0 m² |

## D. Rankings (2021–2025)

Most expensive (median €/m²): **6th (14 831)**, 7th (14 543), 4th (13 027),
1st (12 864), 8th (12 600). Least expensive: 19th (8 681), 20th (8 897),
13th (9 200). No arrondissement fell below the minimum sample size
(`MIN_RANKING_SAMPLE = 30`), so all 20 are ranked (empty warnings).

## E. Paris DPE distribution 2021–2025 (dwelling-unit, label-eligible)

Eligible: **730 009**.

| Label | Count | % |
|---|---|---|
| A | 835 | 0.11 |
| B | 8 797 | 1.21 |
| C | 169 508 | 23.22 |
| D | 227 274 | 31.13 |
| E | 194 895 | 26.70 |
| F | 77 760 | 10.65 |
| G | 50 940 | 6.98 |

**F+G (passoires thermiques): 128 700 = 17.63 %** — cohérent avec les
estimations nationales sur le parc parisien.

## F. DPE intensity summary (dwelling-unit, intensity-eligible)

| Metric | Value |
|---|---|
| Eligible records | 730 009 |
| Median consumption | 240.80 kWh/m²/yr |
| Consumption P25 / P75 | 177.50 / 312.80 |
| Median emissions | 25.00 kgCO₂/m²/yr |
| Emissions P25 / P75 | 11.00 / 47.00 |
| Median surface | 45.0 m² |

## G. Arrondissement 15 profile (combined at result level)

Market median 10 087.72 €/m² (15 590 market tx); DPE eligible 82 414, F+G 16.52 %;
median consumption 241.9. Market and DPE come from independent queries on the
shared arrondissement — no record-level DVF/DPE join.

## Performance

| Query | Time (ms) |
|---|---|
| market_overview | 1 192 |
| price_trend | 747 |
| compare 13/20 | 235 |
| rankings | 945 |
| dpe_distribution | 1 032 |
| dpe_intensity | 2 596 |
| area_profile 15 | 1 540 |

Acceptable on ~1M rows with database-side aggregation. `dpe_intensity` is the
slowest (3 medians + 6 quartiles over 730k rows).

## Index usage (EXPLAIN ANALYZE)

- **Market query**: uses an index — Bitmap Heap Scan on `dvf_mutations` with
  `Recheck Cond: (arrondissement = 15 AND is_price_per_m2_eligible)`, i.e. the
  partial index `idx_dvf_price_eligible` / `idx_dvf_arr_year` are exercised.
- **DPE query**: uses parallel aggregation with index access
  (`etiquette_dpe_norm` grouping, `idx_dpe_label_eligible` / `idx_dpe_arr_year`).

Both core queries use index scans; no sequential full-table scan on the hot path.

## Proposed indexes (not added)

**None.** The execution plans show the approved indexes are used and timings are
acceptable. No new index is justified at this stage; any future proposal would be
documented here before being added.

## Limitations

- Plausibility band `[1000, 50000] €/m²` is deliberate and configurable; the raw
  median is always reported alongside for transparency.
- DVF/DPE combined only at arrondissement + period aggregate level.
- 2026 DPE is partial and excluded by default.
