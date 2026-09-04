"""Parameterized SQL queries for analytics (PostgreSQL aggregates).

All medians/quartiles use percentile_cont in the database; the million-row
tables are never loaded into Pandas. Every query uses bound parameters; no SQL
is built by string-concatenating user input.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, text

from real_estate_agent.analytics import policy

SCHEMA = "real_estate"


def _market_where(arrondissement: int | None) -> tuple[str, dict[str, Any]]:
    """Build the shared WHERE clause and params for market queries."""
    clauses = [
        "source_year BETWEEN :start_year AND :end_year",
    ]
    params: dict[str, Any] = {}
    if arrondissement is not None:
        clauses.append("arrondissement = :arr")
        params["arr"] = arrondissement
    return " AND ".join(clauses), params


def market_overview_row(
    engine: Engine, arrondissement: int | None, start_year: int, end_year: int
) -> dict[str, Any]:
    """Return the aggregate market row for an area/period.

    Computes counts and medians in a single pass using FILTER clauses so the raw
    eligible median and the plausibility-filtered market median come from one
    query.
    """
    where, params = _market_where(arrondissement)
    params.update({
        "start_year": start_year, "end_year": end_year,
        "pmin": policy.PRICE_PER_M2_MIN, "pmax": policy.PRICE_PER_M2_MAX,
    })
    sql = text(f"""
        SELECT
            count(*) AS total_tx,
            count(*) FILTER (WHERE is_price_per_m2_eligible) AS eligible_tx,
            count(*) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw >= :pmin
                  AND price_per_m2_raw <= :pmax
            ) AS market_tx,
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY price_per_m2_raw
            ) FILTER (WHERE is_price_per_m2_eligible) AS raw_median,
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY price_per_m2_raw
            ) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw >= :pmin
                  AND price_per_m2_raw <= :pmax
            ) AS market_median,
            percentile_cont(0.25) WITHIN GROUP (
                ORDER BY price_per_m2_raw
            ) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw >= :pmin
                  AND price_per_m2_raw <= :pmax
            ) AS price_p25,
            percentile_cont(0.75) WITHIN GROUP (
                ORDER BY price_per_m2_raw
            ) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw >= :pmin
                  AND price_per_m2_raw <= :pmax
            ) AS price_p75,
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY residential_surface
            ) FILTER (WHERE residential_surface IS NOT NULL) AS median_surface
        FROM {SCHEMA}.dvf_mutations
        WHERE {where}
    """)
    with engine.connect() as conn:
        row = conn.execute(sql, params).mappings().first()
    return dict(row) if row else {}


def price_trend_rows(
    engine: Engine, arrondissement: int | None, start_year: int, end_year: int
) -> list[dict[str, Any]]:
    """Return one aggregate row per year for the price trend."""
    where, params = _market_where(arrondissement)
    params.update({
        "start_year": start_year, "end_year": end_year,
        "pmin": policy.PRICE_PER_M2_MIN, "pmax": policy.PRICE_PER_M2_MAX,
    })
    sql = text(f"""
        SELECT
            source_year AS year,
            count(*) AS tx_count,
            count(*) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw BETWEEN :pmin AND :pmax
            ) AS market_count,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS median_price,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS p25,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS p75
        FROM {SCHEMA}.dvf_mutations
        WHERE {where}
        GROUP BY source_year
        ORDER BY source_year
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).mappings().all()]


def area_metrics_rows(
    engine: Engine, arrondissements: list[int], start_year: int, end_year: int
) -> list[dict[str, Any]]:
    """Return market metrics per arrondissement for a comparison."""
    params: dict[str, Any] = {
        "start_year": start_year, "end_year": end_year,
        "pmin": policy.PRICE_PER_M2_MIN, "pmax": policy.PRICE_PER_M2_MAX,
        "areas": tuple(arrondissements),
    }
    sql = text(f"""
        SELECT
            arrondissement,
            count(*) AS total_tx,
            count(*) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw BETWEEN :pmin AND :pmax
            ) AS market_tx,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS median_price,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS p25,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS p75,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY residential_surface)
                FILTER (WHERE residential_surface IS NOT NULL) AS median_surface
        FROM {SCHEMA}.dvf_mutations
        WHERE source_year BETWEEN :start_year AND :end_year
          AND arrondissement IN :areas
        GROUP BY arrondissement
        ORDER BY arrondissement
    """).bindparams()
    # expanding=True lets an IN clause take a tuple safely (parameterized).
    sql = sql.bindparams(_expanding_areas(arrondissements))
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).mappings().all()]


def _expanding_areas(_areas: list[int]):  # noqa: ANN202
    """Return a bindparam marker enabling a safe expanding IN clause."""
    from sqlalchemy import bindparam

    return bindparam("areas", expanding=True)


def ranking_rows(
    engine: Engine, start_year: int, end_year: int
) -> list[dict[str, Any]]:
    """Return per-arrondissement market metrics for all 20 arrondissements."""
    params: dict[str, Any] = {
        "start_year": start_year, "end_year": end_year,
        "pmin": policy.PRICE_PER_M2_MIN, "pmax": policy.PRICE_PER_M2_MAX,
    }
    sql = text(f"""
        SELECT
            arrondissement,
            count(*) FILTER (
                WHERE is_price_per_m2_eligible
                  AND price_per_m2_raw BETWEEN :pmin AND :pmax
            ) AS market_count,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_m2_raw)
                FILTER (
                    WHERE is_price_per_m2_eligible
                      AND price_per_m2_raw BETWEEN :pmin AND :pmax
                ) AS median_price,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY residential_surface)
                FILTER (WHERE residential_surface IS NOT NULL) AS median_surface
        FROM {SCHEMA}.dvf_mutations
        WHERE source_year BETWEEN :start_year AND :end_year
          AND arrondissement IS NOT NULL
        GROUP BY arrondissement
        ORDER BY arrondissement
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).mappings().all()]


def dpe_distribution_row(
    engine: Engine, arrondissement: int | None, start_year: int, end_year: int
) -> dict[str, Any]:
    """Return A-G counts for dwelling-unit, label-eligible DPE records."""
    clauses = [
        "is_label_analysis_eligible",
        "analysis_population = 'dwelling_unit'",
        "diagnostic_year BETWEEN :start_year AND :end_year",
    ]
    params: dict[str, Any] = {"start_year": start_year, "end_year": end_year}
    if arrondissement is not None:
        clauses.append("arrondissement = :arr")
        params["arr"] = arrondissement
    where = " AND ".join(clauses)
    sql = text(f"""
        SELECT etiquette_dpe_norm AS label, count(*) AS n
        FROM {SCHEMA}.dpe_diagnostics
        WHERE {where}
        GROUP BY etiquette_dpe_norm
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return {r["label"]: int(r["n"]) for r in rows if r["label"] is not None}


def dpe_intensity_row(
    engine: Engine, arrondissement: int | None, start_year: int, end_year: int
) -> dict[str, Any]:
    """Return consumption/emission/surface aggregates for intensity DPE."""
    clauses = [
        "is_intensity_analysis_eligible",
        "analysis_population = 'dwelling_unit'",
        "diagnostic_year BETWEEN :start_year AND :end_year",
    ]
    params: dict[str, Any] = {"start_year": start_year, "end_year": end_year}
    if arrondissement is not None:
        clauses.append("arrondissement = :arr")
        params["arr"] = arrondissement
    where = " AND ".join(clauses)
    sql = text(f"""
        SELECT
            count(*) AS n,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY conso_5_usages_par_m2_ep) AS med_conso,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY conso_5_usages_par_m2_ep) AS conso_p25,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY conso_5_usages_par_m2_ep) AS conso_p75,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY emission_ges_5_usages_par_m2) AS med_emis,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY emission_ges_5_usages_par_m2) AS emis_p25,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY emission_ges_5_usages_par_m2) AS emis_p75,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY surface_habitable_logement) AS med_surface
        FROM {SCHEMA}.dpe_diagnostics
        WHERE {where}
    """)
    with engine.connect() as conn:
        row = conn.execute(sql, params).mappings().first()
    return dict(row) if row else {}
