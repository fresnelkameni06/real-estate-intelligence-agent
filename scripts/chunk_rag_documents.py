"""Create traceable JSONL chunks from Phase 6.2 processed RAG documents.

Usage (from the repository root):
    py scripts/chunk_rag_documents.py
    py scripts/chunk_rag_documents.py --source-id comprendre_mon_dpe
    py scripts/chunk_rag_documents.py --force
    py scripts/chunk_rag_documents.py --target-characters 1400
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from real_estate_agent.ingestion.documents.registry import (
    RegistryError,
    enabled_sources,
    load_registry,
)
from real_estate_agent.rag.chunking.models import ChunkingConfig
from real_estate_agent.rag.chunking.pipeline import run_chunking
from real_estate_agent.rag.chunking.splitter import ChunkingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("chunk_rag")

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "rag_sources.json"
PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "documents"
OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "chunks"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chunk processed RAG documents to JSONL.")
    parser.add_argument("--source-id", help="Chunk only this enabled source_id.")
    parser.add_argument("--force", action="store_true", help="Regenerate unchanged chunks.")
    parser.add_argument("--target-characters", type=int, default=1400)
    parser.add_argument("--maximum-characters", type=int, default=1800)
    parser.add_argument("--overlap-characters", type=int, default=200)
    parser.add_argument("--minimum-chunk-characters", type=int, default=120)
    parser.add_argument("--short-document-warning-threshold", type=int, default=1000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = ChunkingConfig(
            target_characters=args.target_characters,
            maximum_characters=args.maximum_characters,
            overlap_characters=args.overlap_characters,
            minimum_chunk_characters=args.minimum_chunk_characters,
            short_document_warning_threshold=args.short_document_warning_threshold,
        )
        sources = enabled_sources(load_registry(REGISTRY_PATH))
    except (ValidationError, RegistryError) as exc:
        logger.error("Initialization failed: %s", exc)
        return 2

    if args.source_id:
        sources = [source for source in sources if source.source_id == args.source_id]
        if not sources:
            logger.error("No enabled source with source_id '%s'.", args.source_id)
            return 2

    try:
        results, manifest = run_chunking(
            sources,
            PROCESSED_DIR,
            OUTPUT_DIR,
            config,
            force=args.force,
            output_root=REPO_ROOT,
        )
    except ChunkingError as exc:
        logger.error("Chunk corpus initialization failed: %s", exc)
        return 2

    failed = 0
    for result in results:
        if result["status"] == "failed":
            failed += 1
            logger.error("%s: failed — %s", result["source_id"], result["error"])
            continue
        flags = ",".join(result["quality_flags"]) or "none"
        logger.info(
            "%s: %s — %d chunks, min=%d, avg=%.1f, max=%d, flags=%s",
            result["source_id"],
            result["status"],
            result["chunk_count"],
            result["minimum_chunk_size"],
            result["average_chunk_size"],
            result["maximum_chunk_size"],
            flags,
        )
    logger.info(
        "Done: %d successful, %d failed, %d total chunks. Output -> %s",
        len(results) - failed,
        failed,
        manifest.total_chunks,
        OUTPUT_DIR,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
