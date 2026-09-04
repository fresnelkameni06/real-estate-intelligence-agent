"""Run the Paris DPE data-engineering pipeline.

Acquires the complete Paris (department 75) DPE snapshot via the ADEME API (or
reuses a valid local snapshot), transforms it into one deterministically selected
row per numero_dpe, and writes a Parquet dataset plus a quality report.

Usage (inside venv3):
    py scripts/run_dpe_pipeline.py            # reuse snapshot if valid
    py scripts/run_dpe_pipeline.py --refresh  # force a fresh API snapshot

The processed dataset contains no complete textual address. DPE and DVF are NOT
aggregated together in this phase.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from real_estate_agent.ingestion.dpe.client import acquire_snapshot
from real_estate_agent.processing.dpe.quality import build_report
from real_estate_agent.processing.dpe.transformer import (
    add_quality_flags,
    load_snapshot_frame,
    observed_building_types,
    resolve_duplicates,
    select_processed_columns,
    validate_schema,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dpe_pipeline")

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "dpe"
PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "dpe"
DOCS_DIR = REPO_ROOT / "docs" / "data-engineering"

SNAPSHOT = RAW_DIR / "dpe_75_snapshot.json"
OUT_PARQUET = PROCESSED_DIR / "dpe_diagnostics.parquet"
QUALITY_JSON = PROCESSED_DIR / "dpe_quality_report.json"
QUALITY_MD = DOCS_DIR / "DPE_QUALITY_REPORT.md"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_markdown(report: dict) -> None:
    """Human-readable report (aggregates only, no addresses)."""
    lines: list[str] = ["# DPE Quality Report — Paris\n"]
    lines.append(f"> Generated {_utc_now_iso()}. Aggregated statistics only. "
                 "This dataset represents available diagnostics, NOT the full "
                 "Paris housing stock.\n")
    lines.append("## Extraction\n")
    lines.append(f"- API total announced: {report['api_total_announced']}")
    lines.append(f"- Rows retrieved: {report['rows_retrieved']}")
    lines.append(f"- Pagination pages: {report['pagination_pages']}")
    lines.append(f"- Processed rows: {report['processed_rows']}")
    lines.append(f"- Label-analysis eligible: {report['label_analysis_eligible_rows']}")
    lines.append(f"- Intensity-analysis eligible: "
                 f"{report['intensity_analysis_eligible_rows']}")
    lines.append(f"- Exact duplicates: {report['exact_duplicates']}")
    lines.append(f"- Unique numero_dpe: {report['unique_numero_dpe']}")
    lines.append(f"- Missing numero_dpe: {report['missing_numero_dpe']}")
    lines.append(f"- Conflicting duplicates: {report['conflicting_duplicates']}")
    lines.append(f"- Establishment date range: {report['establishment_date_min']} "
                 f"→ {report['establishment_date_max']}")
    lines.append(f"- Complete analysis years (2021–2025): "
                 f"{report['complete_analysis_year_count_2021_2025']}")
    lines.append(f"- Partial year (2026): {report['partial_year_count_2026']}")
    lines.append(f"- Coordinate coverage: {report['coordinate_coverage_pct']} %")
    lines.append(f"- Arrondissements covered: {report['arrondissements_covered']} / 20")
    lines.append(f"- INSEE/postal inconsistencies: "
                 f"{report['insee_postal_inconsistencies']}\n")

    lines.append("## Analysis populations\n")
    lines.append(f"- Apartments (dwelling_unit): {report['apartment_count']}")
    lines.append(f"- Houses (dwelling_unit): {report['house_count']}")
    lines.append(f"- Whole-building (immeuble): {report['whole_building_count']}")
    for k, v in report["analysis_population_counts"].items():
        lines.append(f"- population '{k}': {v}")

    lines.append("\n## DPE label distribution\n")
    for k, v in report["dpe_label_distribution"].items():
        lines.append(f"- {k}: {v}")
    lines.append("\n## GES label distribution\n")
    for k, v in report["ges_label_distribution"].items():
        lines.append(f"- {k}: {v}")

    lines.append("\n## Building type (observed raw)\n")
    for k, v in report["building_type_distribution_raw"].items():
        lines.append(f"- {k}: {v}")

    lines.append("\n## Counts by arrondissement\n")
    for k, v in report["counts_by_arrondissement"].items():
        lines.append(f"- Arr {k}: {v}")

    lines.append("\n## Label-analysis exclusions by reason\n")
    for k, v in report["label_exclusions_by_reason"].items():
        lines.append(f"- {k}: {v}")

    lines.append("\n## Intensity-analysis exclusions by reason\n")
    for k, v in report["intensity_exclusions_by_reason"].items():
        lines.append(f"- {k}: {v}")

    lines.append("\n## Surface quantiles (m²)\n")
    for k, v in report["surface_quantiles"].items():
        lines.append(f"- {k}: {round(v, 2) if isinstance(v, float) else v}")

    lines.append("\n## Outlier policy\n")
    lines.append(f"{report['outlier_policy']}")

    QUALITY_MD.parent.mkdir(parents=True, exist_ok=True)
    QUALITY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Paris DPE pipeline.")
    parser.add_argument("--refresh", action="store_true",
                        help="Force a fresh API snapshot instead of reusing local.")
    args = parser.parse_args(argv)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Acquiring DPE snapshot (refresh=%s) ...", args.refresh)
    manifest = acquire_snapshot(RAW_DIR, refresh=args.refresh)

    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    results = payload.get("results", [])
    logger.info("Loaded %d snapshot rows", len(results))

    df = load_snapshot_frame(results)
    validate_schema(df)
    observed_types = observed_building_types(df)

    resolved, dedup_stats = resolve_duplicates(df)
    flagged = add_quality_flags(resolved)
    processed = select_processed_columns(flagged)

    processed.to_parquet(OUT_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUT_PARQUET.name, len(processed))

    report = build_report(flagged, manifest, dedup_stats, observed_types)
    QUALITY_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _write_markdown(report)
    logger.info("Quality report -> %s and %s", QUALITY_JSON, QUALITY_MD)
    logger.info("DPE pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
