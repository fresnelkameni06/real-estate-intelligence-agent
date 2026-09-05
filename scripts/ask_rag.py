"""Ask a documentary question and print a concise grounded answer with sources.

Examples:
    py scripts/ask_rag.py "Combien de temps un DPE est-il valable ?"
    py scripts/ask_rag.py "Explique en détail les restrictions pour un logement G."
    py scripts/ask_rag.py "Résume le rôle du DPE." --style brief
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
from real_estate_agent.rag.generation.config import RagGenerationSettings
from real_estate_agent.rag.generation.prompts import RagPromptError
from real_estate_agent.rag.generation.provider import (
    OpenAIResponsesGenerator,
    ResponseGenerationError,
)
from real_estate_agent.rag.generation.service import RagAnswerService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
for noisy_logger in ("httpx", "httpx2", "openai"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger("ask_rag")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a grounded answer from indexed official documents."
    )
    parser.add_argument("question", help="Natural-language documentary question.")
    parser.add_argument(
        "--style",
        choices=("auto", "brief", "detailed"),
        default="auto",
        help="Answer detail; auto follows the wording of the question.",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        help="Optional source filter; repeat for multiple sources.",
    )
    parser.add_argument(
        "--show-passages",
        action="store_true",
        help="Display cited passage identifiers and similarity scores for debugging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = None
    try:
        embedding_settings = EmbeddingSettings()
        generation_settings = RagGenerationSettings()
        api_key = generation_settings.require_api_key()
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=api_key,
            model=embedding_settings.model,
            dimensions=embedding_settings.dimensions,
            timeout_seconds=embedding_settings.timeout_seconds,
        )
        response_generator = OpenAIResponsesGenerator(
            api_key=api_key,
            model=generation_settings.model,
            timeout_seconds=generation_settings.timeout_seconds,
        )
        engine = make_engine(load_settings().require_database_url())
        service = RagAnswerService(
            embedding_provider=embedding_provider,
            repository=PgVectorRepository(engine),
            response_generator=response_generator,
            top_k=generation_settings.retrieval_top_k,
            minimum_similarity=generation_settings.minimum_similarity,
            context_max_characters=generation_settings.context_max_characters,
            max_output_tokens=generation_settings.max_output_tokens,
        )
        result = service.answer(
            args.question,
            style=args.style,
            source_ids=args.source_id,
        )
    except (
        EmbeddingProviderError,
        RagPromptError,
        ResponseGenerationError,
        RuntimeError,
        SQLAlchemyError,
        ValidationError,
        ValueError,
    ) as exc:
        logger.error("RAG answer failed: %s", exc)
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    print(f"\n{result.answer}")
    if result.citations:
        print("\nSources :")
        grouped: dict[tuple[str, str, str], list] = {}
        for citation in result.citations:
            key = (citation.url, citation.title, citation.publisher)
            grouped.setdefault(key, []).append(citation)
        for (url, title, publisher), citations in grouped.items():
            markers = " ".join(f"[{citation.citation_id}]" for citation in citations)
            pages = sorted(
                {citation.page_start for citation in citations if citation.page_start}
            )
            page = f", page(s) {', '.join(map(str, pages))}" if pages else ""
            print(
                f"{markers} {title} — {publisher}{page}\n"
                f"     {url}"
            )
        if args.show_passages:
            print("\nPassages utilisés :")
            for citation in result.citations:
                print(
                    f"[{citation.citation_id}] chunk={citation.chunk_id} | "
                    f"similarity={citation.similarity:.4f} | section={citation.section}"
                )
    elif result.insufficient_context:
        print("\nAucune source suffisamment pertinente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
