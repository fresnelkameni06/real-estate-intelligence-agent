"""Process acquired raw RAG documents into structured JSON.

Usage (from the repository root):
    py scripts/process_rag_documents.py
    py scripts/process_rag_documents.py --source-id comprendre_mon_dpe
    py scripts/process_rag_documents.py --force
    py scripts/process_rag_documents.py --min-characters 200

Uses the existing source registry and acquisition manifest. Writes one JSON per
source under data/processed/documents/ (Git-ignored).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from real_estate_agent.ingestion.documents.registry import (
    RegistryError,
    enabled_sources,
    load_registry,
)
from real_estate_agent.processing.documents.pipeline import (
    DEFAULT_MIN_CHARACTERS,
    ProcessingError,
    load_manifest,
    process_source,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("process_rag")

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "rag_sources.json"
RAW_DIR = REPO_ROOT / "data" / "raw" / "documents"
PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "documents"
MANIFEST_PATH = RAW_DIR / "manifest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process RAG documents to JSON.")
    parser.add_argument("--source-id", help="Process only this source_id.")
    parser.add_argument("--force", action="store_true",
                        help="Reprocess even if the raw checksum is unchanged.")
    parser.add_argument("--min-characters", type=int, default=DEFAULT_MIN_CHARACTERS)
    args = parser.parse_args(argv)

    try:
        registry = load_registry(REGISTRY_PATH)
        manifest = load_manifest(MANIFEST_PATH)
    except (RegistryError, ProcessingError) as exc:
        logger.error("%s", exc)
        return 2

    sources = enabled_sources(registry)
    if args.source_id:
        sources = [s for s in sources if s.source_id == args.source_id]
        if not sources:
            logger.error("No enabled source with source_id '%s'.", args.source_id)
            return 2

    processed = 0
    unchanged = 0
    failed = 0
    for s in sources:
        res = process_source(
            s, RAW_DIR, PROCESSED_DIR, manifest,
            min_characters=args.min_characters, force=args.force,
        )
        status = res["status"]
        if status == "processed":
            processed += 1
            logger.info("  %s: processed (%d chars)", s.source_id, res["chars"])
        elif status == "unchanged":
            unchanged += 1
            logger.info("  %s: unchanged", s.source_id)
        else:
            failed += 1
            logger.warning("  %s: FAILED — %s", s.source_id, res["error"])

    logger.info("Done: %d processed, %d unchanged, %d failed.",
                processed, unchanged, failed)
    # Non-zero only if nothing succeeded (all failed) while some were attempted.
    if sources and (processed + unchanged) == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
