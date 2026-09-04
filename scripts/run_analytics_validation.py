"""Run the analytics engine against the real development database.

Reports aggregate results only (no addresses, no individual transactions), and
checks invariants. Also times the main queries and runs EXPLAIN ANALYZE on the
core market and DPE queries to confirm index usage.

Usage:
    py scripts/run_analytics_validation.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import text

from real_estate_agent.analytics import policy, service
from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("analytics_validation")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "real_estate"


def _time(label: str, fn):  # noqa: ANN001
    start = time.perf_counter()
    result = fn()
    ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info("%s: %s ms", label, ms)
    return result, ms


def main() -> int:
    settings = load_settings()
    engine = make_engine(settings.require_database_url())

    out: dict[str, object] = {"timings_ms": {}, "invariants": {}}
    invariants_ok = True

    # A. Paris market overview 2021-2025
    overview, t = _time("market_overview_paris",
                        lambda: service.get_market_overview(engine))
    out["timings_ms"]["market_overview"] = t
    out["market_overview"] = overview.model_dump()

    # market <= eligible <= total
    inv = (overview.market_analysis_transactions
           <= overview.price_eligible_transactions
           <= overview.total_residential_transactions)
    out["invariants"]["market_le_eligible_le_total"] = inv
    invariants_ok = invariants_ok and inv

    # B. Annual trend
    trend, t = _time("price_trend_paris",
                     lambda: service.get_price_trend(engine))
    out["timings_ms"]["price_trend"] = t
    out["price_trend"] = trend.model_dump()

    # C. Compare 13 vs 20
    cmp, t = _time("compare_13_20",
                   lambda: service.compare_arrondissements(engine, [13, 20]))
    out["timings_ms"]["compare"] = t
    out["compare_13_20"] = cmp.model_dump()

    # D. Rankings
    rankings, t = _time("rankings", lambda: service.get_area_rankings(engine))
    out["timings_ms"]["rankings"] = t
    out["rankings"] = rankings.model_dump()
    # all arrondissements 1..20
    all_arr = {e.arrondissement for e in rankings.by_transaction_volume}
    inv_arr = all(1 <= a <= 20 for a in all_arr)
    out["invariants"]["arrondissements_in_range"] = inv_arr
    invariants_ok = invariants_ok and inv_arr

    # E. DPE distribution 2021-2025
    dist, t = _time("dpe_distribution_paris",
                    lambda: service.get_dpe_distribution(engine))
    out["timings_ms"]["dpe_distribution"] = t
    out["dpe_distribution"] = dist.model_dump()
    inv_fg = dist.fg_count <= dist.eligible_dpe_count
    pct_sum = sum(dist.percentages.values())
    inv_pct = abs(pct_sum - 100.0) < 0.5 or dist.eligible_dpe_count == 0
    out["invariants"]["fg_le_eligible"] = inv_fg
    out["invariants"]["percentages_sum_100"] = inv_pct
    out["invariants"]["default_excludes_partial_2026"] = (
        dist.includes_partial_year is False
    )
    invariants_ok = invariants_ok and inv_fg and inv_pct

    # F. DPE intensity
    intensity, t = _time("dpe_intensity_paris",
                         lambda: service.get_dpe_intensity_summary(engine))
    out["timings_ms"]["dpe_intensity"] = t
    out["dpe_intensity"] = intensity.model_dump()

    # G. Area profile 15
    profile, t = _time("area_profile_15",
                       lambda: service.get_area_profile(engine, 15))
    out["timings_ms"]["area_profile"] = t
    out["area_profile_15"] = profile.model_dump()

    # EXPLAIN ANALYZE on the core market and DPE queries.
    out["explain"] = _explain(engine)

    out["all_invariants_passed"] = invariants_ok
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if invariants_ok else 1


def _explain(engine) -> dict[str, object]:  # noqa: ANN001
    """Run EXPLAIN ANALYZE on the main market and DPE queries; report index use."""
    market_sql = text(f"""
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_m2_raw)
        FROM {SCHEMA}.dvf_mutations
        WHERE source_year BETWEEN 2021 AND 2025 AND arrondissement = 15
          AND is_price_per_m2_eligible
          AND price_per_m2_raw BETWEEN :pmin AND :pmax
    """)
    dpe_sql = text(f"""
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT etiquette_dpe_norm, count(*)
        FROM {SCHEMA}.dpe_diagnostics
        WHERE is_label_analysis_eligible
          AND analysis_population = 'dwelling_unit'
          AND diagnostic_year BETWEEN 2021 AND 2025
          AND arrondissement = 15
        GROUP BY etiquette_dpe_norm
    """)
    result: dict[str, object] = {}
    with engine.connect() as conn:
        for name, sql, params in (
            ("market", market_sql, {"pmin": policy.PRICE_PER_M2_MIN,
                                    "pmax": policy.PRICE_PER_M2_MAX}),
            ("dpe", dpe_sql, {}),
        ):
            plan = [r[0] for r in conn.execute(sql, params).all()]
            uses_index = any("Index" in line for line in plan)
            result[name] = {
                "uses_index_scan": uses_index,
                "plan": plan,
            }
    return result


if __name__ == "__main__":
    sys.exit(main())
