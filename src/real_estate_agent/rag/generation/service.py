"""Retrieve official passages and generate a bounded, cited answer."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from real_estate_agent.rag.embeddings.models import SearchHit
from real_estate_agent.rag.embeddings.provider import EmbeddingProvider
from real_estate_agent.rag.generation.models import AnswerStyle, RagAnswerResult
from real_estate_agent.rag.generation.prompts import (
    INSUFFICIENT_CONTEXT_MARKER,
    SYSTEM_INSTRUCTIONS,
    build_grounded_input,
    citations_from_answer,
)
from real_estate_agent.rag.generation.provider import ResponseGenerator


class SearchRepository(Protocol):
    """Minimal vector-search contract required by the answer service."""

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        source_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]: ...


class RagAnswerService:
    """Single-question RAG flow with adaptive detail and verified citations."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        repository: SearchRepository,
        response_generator: ResponseGenerator,
        top_k: int = 5,
        minimum_similarity: float = 0.42,
        context_max_characters: int = 12_000,
        max_output_tokens: int = 1600,
    ) -> None:
        if not 1 <= top_k <= 8:
            raise ValueError("top_k must be between 1 and 8.")
        if not -1.0 <= minimum_similarity <= 1.0:
            raise ValueError("minimum_similarity must be between -1 and 1.")
        if context_max_characters < 2_000:
            raise ValueError("context_max_characters must be at least 2000.")
        if max_output_tokens < 100:
            raise ValueError("max_output_tokens must be at least 100.")
        self._embedding_provider = embedding_provider
        self._repository = repository
        self._response_generator = response_generator
        self._top_k = top_k
        self._minimum_similarity = minimum_similarity
        self._context_max_characters = context_max_characters
        self._max_output_tokens = max_output_tokens

    @staticmethod
    def _validate_question(question: str) -> str:
        value = question.strip()
        if not value:
            raise ValueError("The question must not be blank.")
        if len(value) > 2_000:
            raise ValueError("The question must contain at most 2000 characters.")
        return value

    def _abstention(
        self,
        *,
        question: str,
        style: AnswerStyle,
        hits: Sequence[SearchHit],
    ) -> RagAnswerResult:
        top_similarity = hits[0].similarity if hits else None
        return RagAnswerResult(
            question=question,
            answer=(
                "Je ne dispose pas d'informations suffisamment pertinentes dans les "
                "documents officiels indexés pour répondre de façon fiable."
            ),
            citations=[],
            retrieved_chunks=len(hits),
            top_similarity=top_similarity,
            model=self._response_generator.model,
            requested_style=style,
            grounded=True,
            insufficient_context=True,
        )

    def answer(
        self,
        question: str,
        *,
        style: AnswerStyle = "auto",
        source_ids: Sequence[str] | None = None,
    ) -> RagAnswerResult:
        """Answer one documentary question without using unsupported knowledge."""
        validated_question = self._validate_question(question)
        if style not in {"auto", "brief", "detailed"}:
            raise ValueError("style must be auto, brief or detailed.")
        query_vectors = self._embedding_provider.embed([validated_question])
        if len(query_vectors) != 1:
            raise RuntimeError("The embedding provider did not return one query vector.")
        hits = self._repository.search(
            query_vectors[0],
            top_k=self._top_k,
            source_ids=source_ids,
        )
        if not hits or hits[0].similarity < self._minimum_similarity:
            return self._abstention(question=validated_question, style=style, hits=hits)

        input_text, included_hits = build_grounded_input(
            validated_question,
            hits,
            style=style,
            max_characters=self._context_max_characters,
        )
        raw_answer = self._response_generator.generate(
            instructions=SYSTEM_INSTRUCTIONS,
            input_text=input_text,
            max_output_tokens=self._max_output_tokens,
        ).strip()
        insufficient = raw_answer.startswith(INSUFFICIENT_CONTEXT_MARKER)
        answer = (
            raw_answer.removeprefix(INSUFFICIENT_CONTEXT_MARKER).lstrip(" :\n")
            if insufficient
            else raw_answer
        )
        if not answer:
            raise RuntimeError("The generated answer is empty after validation.")
        citations = citations_from_answer(
            answer,
            included_hits,
            allow_none=insufficient,
        )
        return RagAnswerResult(
            question=validated_question,
            answer=answer,
            citations=citations,
            retrieved_chunks=len(included_hits),
            top_similarity=included_hits[0].similarity,
            model=self._response_generator.model,
            requested_style=style,
            grounded=True,
            insufficient_context=insufficient,
        )
