"""Run a semantic pgvector search without generating an LLM answer.

Usage:
    py scripts/search_rag.py "Quelles restrictions concernent les logements G ?"
"""

from __future__ import annotations

import argparse
import logging
import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.rag.embeddings.config import EmbeddingSettings
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
logger = logging.getLogger("search_rag")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search the indexed official documents.")
    parser.add_argument("question", help="Natural-language question to embed and search.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results (1-20).")
    parser.add_argument(
        "--source-id",
        action="append",
        help="Optional source filter; repeat for multiple sources.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = None
    try:
        settings = EmbeddingSettings()
        provider = OpenAIEmbeddingProvider(
            api_key=settings.require_api_key(),
            model=settings.model,
            dimensions=settings.dimensions,
            timeout_seconds=settings.timeout_seconds,
        )
        query_vector = provider.embed([args.question])[0]
        engine = make_engine(load_settings().require_database_url())
        hits = PgVectorRepository(engine).search(
            query_vector,
            top_k=args.top_k,
            source_ids=args.source_id,
        )
    except (
        EmbeddingProviderError,
        RuntimeError,
        SQLAlchemyError,
        ValidationError,
        ValueError,
    ) as exc:
        logger.error("Semantic search failed: %s", exc)
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    if not hits:
        logger.warning("No indexed chunk matched the selected filters.")
        return 1
    for rank, hit in enumerate(hits, start=1):
        heading = " > ".join(hit.heading_path) or "Sans titre de section"
        page = f" | page {hit.page_start}" if hit.page_start is not None else ""
        print(
            f"\n[{rank}] similarity={hit.similarity:.4f} | {hit.title}\n"
            f"    source={hit.source_id} | section={heading}{page}\n"
            f"    url={hit.source_page_url}\n"
            f"    {hit.text}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
