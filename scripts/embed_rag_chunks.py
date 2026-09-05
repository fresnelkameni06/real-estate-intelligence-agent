"""Embed Phase 6.3 chunks with OpenAI and synchronize them to pgvector.

Usage (from the repository root):
    py scripts/embed_rag_chunks.py
    py scripts/embed_rag_chunks.py --source-id comprendre_mon_dpe
    py scripts/embed_rag_chunks.py --force
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.rag.embeddings.config import EmbeddingSettings
from real_estate_agent.rag.embeddings.pipeline import (
    EmbeddingPipelineError,
    load_chunk_corpus,
    run_embedding_index,
)
from real_estate_agent.rag.embeddings.provider import (
    EmbeddingProviderError,
    OpenAIEmbeddingProvider,
)
from real_estate_agent.rag.embeddings.repository import PgVectorRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("embed_rag_chunks")

REPO_ROOT = Path(__file__).resolve().parents[1]
CHUNK_DIR = REPO_ROOT / "data" / "processed" / "chunks"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Embed local RAG chunks and synchronize PostgreSQL/pgvector."
    )
    parser.add_argument(
        "--source-id",
        action="append",
        help="Process only this source_id; repeat the option for multiple sources.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate every selected embedding even when unchanged.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = None
    try:
        embedding_settings = EmbeddingSettings()
        chunks = load_chunk_corpus(CHUNK_DIR, source_ids=args.source_id)
        provider = OpenAIEmbeddingProvider(
            api_key=embedding_settings.require_api_key(),
            model=embedding_settings.model,
            dimensions=embedding_settings.dimensions,
            timeout_seconds=embedding_settings.timeout_seconds,
        )
        database_settings = load_settings()
        engine = make_engine(database_settings.require_database_url())
        result = run_embedding_index(
            chunks,
            provider,
            PgVectorRepository(engine),
            batch_size=embedding_settings.batch_size,
            force=args.force,
        )
    except (
        EmbeddingPipelineError,
        EmbeddingProviderError,
        RuntimeError,
        SQLAlchemyError,
        ValidationError,
    ) as exc:
        logger.error("Embedding index failed: %s", exc)
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    logger.info(
        "Done: %d sources, %d total chunks, %d embedded, %d unchanged, "
        "%d stale deleted; model=%s dimensions=%d",
        result.source_count,
        result.total_chunks,
        result.embedded_chunks,
        result.unchanged_chunks,
        result.deleted_stale_chunks,
        result.model,
        result.dimensions,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
