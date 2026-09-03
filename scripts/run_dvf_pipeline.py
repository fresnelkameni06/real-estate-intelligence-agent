"""Run the Paris DVF data-engineering pipeline (2021-2025).

Orchestrates: idempotent acquisition -> per-year load/validate/lineage/dedup ->
residential component table -> mutation-level table -> price eligibility ->
combined Parquet outputs -> quality report (JSON + Markdown).

Usage (inside venv3):
    py scripts/run_dvf_pipeline.py

Exit status is non-zero if a required column is missing or French category
values are corrupted for any year.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from real_estate_agent.ingestion.dvf.downloader import DVF_YEARS, acquire_all
from real_estate_agent.processing.dvf.quality import build_year_metrics
from real_estate_agent.processing.dvf.transformer import (
    SchemaError,
    add_lineage,
    add_price_eligibility,
    build_mutations,
    build_residential_components,
    handle_exact_duplicates,
    load_dvf_csv,
    price_distribution,
    validate_schema,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dvf_pipeline")

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "dvf"
PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "dvf"
DOCS_DIR = REPO_ROOT / "docs" / "data-engineering"

UNITS_PARQUET = PROCESSED_DIR / "dvf_residential_units.parquet"
MUTATIONS_PARQUET = PROCESSED_DIR / "dvf_residential_mutations.parquet"
QUALITY_JSON = PROCESSED_DIR / "dvf_quality_report.json"
QUALITY_MD = DOCS_DIR / "DVF_QUALITY_REPORT.md"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def process_year(year: int, record: dict) -> dict:
    """Load, validate, transform one year; return its artefacts and metrics."""
    raw_path = RAW_ROOT / str(year) / "75.csv.gz"
    sha256 = record["sha256"]
    source_file = f"data/raw/dvf/{year}/75.csv.gz"

    df = load_dvf_csv(raw_path)
    raw_rows = len(df)
    validate_schema(df, year)  # raises SchemaError on failure

    df = add_lineage(df, year, source_file, sha256)
    deduped, dedup_stats = handle_exact_duplicates(df)

    components = build_residential_components(deduped)
    mutations = build_mutations(deduped)
    mutations = add_price_eligibility(mutations)

    metrics = build_year_metrics(raw_rows, dedup_stats, deduped, components, mutations)
    metrics["price_per_m2_distribution"] = price_distribution(mutations)

    return {
        "year": year,
        "components": components,
        "mutations": mutations,
        "metrics": metrics,
    }


def _write_markdown(report: dict) -> None:
    """Write the human-readable quality report (aggregates only, no addresses)."""
    lines: list[str] = []
    lines.append("# DVF Quality Report — Paris 2021–2025\n")
    lines.append(f"> Generated {report['generated_at_utc']}. Aggregates only; "
                 "no address-level or individual-transaction detail.\n")

    g = report["global"]
    lines.append("## Global\n")
    lines.append(f"- Raw rows: {g['raw_rows']}")
    lines.append(f"- Exact duplicates: {g['exact_duplicates']}")
    lines.append(f"- Deduplicated rows: {g['deduplicated_rows']}")
    lines.append(f"- Unique mutations: {g['unique_mutations']}")
    lines.append(f"- Residential mutations: {g['residential_mutations']}")
    lines.append(f"- Residential units: {g['residential_units']}")
    lines.append(f"- Single-unit mutations: {g['single_unit_mutations']}")
    lines.append(f"- Multi-unit mutations: {g['multi_unit_mutations']}")
    lines.append(f"- Apartments: {g['apartment_count']} | Houses: {g['house_count']}")
    lines.append(f"- Price/m² eligible: {g['price_eligible_count']} "
                 f"({g['price_eligibility_rate_pct']} %)")
    lines.append(f"- Coordinate coverage: {g['coordinate_coverage_pct']} %\n")

    dist = g.get("price_per_m2_distribution", {})
    if dist.get("count"):
        lines.append("### Global price/m² distribution (raw, eligible)\n")
        for k in ("min", "p0_1", "p0_5", "p1", "p5", "p25", "median",
                  "p75", "p95", "p99", "p99_5", "p99_9", "max"):
            if k in dist:
                lines.append(f"- {k}: {round(dist[k], 2)}")
        lines.append(f"- count: {dist['count']}\n")

    lines.append("## By year\n")
    for year in sorted(report["by_year"]):
        m = report["by_year"][year]
        lines.append(f"### {year}\n")
        lines.append(f"- Raw rows: {m['raw_rows']} | duplicates: "
                     f"{m['exact_duplicates']} | deduped: {m['deduplicated_rows']}")
        lines.append(f"- Unique mutations: {m['unique_mutations']} | residential: "
                     f"{m['residential_mutations']}")
        lines.append(f"- Single-unit: {m['single_unit_mutations']} | multi-unit: "
                     f"{m['multi_unit_mutations']}")
        lines.append(f"- Price/m² eligible: {m['price_eligible_count']} "
                     f"({m['price_eligibility_rate_pct']} %)")
        lines.append(f"- Coordinate coverage: {m['coordinate_coverage_pct']} %\n")

    QUALITY_MD.parent.mkdir(parents=True, exist_ok=True)
    QUALITY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _aggregate_global(
    by_year: dict, all_mutations: pd.DataFrame, all_components: pd.DataFrame
) -> dict:
    """Sum per-year metrics and compute global distributions.

    Coordinate coverage uses the SAME population and grain as the per-year
    metric -- residential components -- so the global figure is consistent with
    the annual ones (both are coverage over residential component rows).
    """
    keys_sum = [
        "raw_rows", "exact_duplicates", "deduplicated_rows", "unique_mutations",
        "residential_mutations", "residential_units", "single_unit_mutations",
        "multi_unit_mutations", "apartment_count", "house_count",
        "invalid_paris_codes", "inconsistent_mutation_values",
        "ambiguous_geography", "invalid_or_missing_surfaces",
        "price_eligible_count",
    ]
    g = {k: int(sum(m[k] for m in by_year.values())) for k in keys_sum}
    total_res_mut = g["residential_mutations"]
    g["price_eligibility_rate_pct"] = (
        round(g["price_eligible_count"] / total_res_mut * 100, 2)
        if total_res_mut else 0.0
    )
    # Global coordinate coverage over residential COMPONENTS (same definition as
    # the per-year metric), not over mutations (whose coords are null for
    # multi-unit mutations, which would understate coverage).
    g["coordinate_coverage_pct"] = (
        round(
            all_components[["longitude", "latitude"]].notna().all(axis=1).mean() * 100,
            2,
        )
        if not all_components.empty else 0.0
    )
    g["price_per_m2_distribution"] = price_distribution(all_mutations)
    return g


def main() -> int:
    """Execute the pipeline; return a process exit code."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Acquiring DVF raw files (idempotent) ...")
    manifest = acquire_all(RAW_ROOT, DVF_YEARS)

    by_year: dict[int, dict] = {}
    all_components: list[pd.DataFrame] = []
    all_mutations: list[pd.DataFrame] = []

    try:
        for year in DVF_YEARS:
            record = manifest["files"][str(year)]
            logger.info("Processing year %s ...", year)
            result = process_year(year, record)
            by_year[year] = result["metrics"]
            all_components.append(result["components"])
            all_mutations.append(result["mutations"])
    except SchemaError as exc:
        logger.error("Schema/encoding validation failed: %s", exc)
        return 1

    components_df = pd.concat(all_components, ignore_index=True)
    mutations_df = pd.concat(all_mutations, ignore_index=True)

    components_df.to_parquet(UNITS_PARQUET, index=False)
    mutations_df.to_parquet(MUTATIONS_PARQUET, index=False)
    logger.info("Wrote %s (%d rows) and %s (%d rows)",
                UNITS_PARQUET.name, len(components_df),
                MUTATIONS_PARQUET.name, len(mutations_df))

    global_metrics = _aggregate_global(by_year, mutations_df, components_df)
    report = {
        "generated_at_utc": _utc_now_iso(),
        "years": list(DVF_YEARS),
        "global": global_metrics,
        "by_year": by_year,
        "output_sizes_bytes": {
            "dvf_residential_units.parquet": UNITS_PARQUET.stat().st_size,
            "dvf_residential_mutations.parquet": MUTATIONS_PARQUET.stat().st_size,
        },
    }
    QUALITY_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _write_markdown(report)
    logger.info("Quality report -> %s and %s", QUALITY_JSON, QUALITY_MD)
    logger.info("DVF pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
