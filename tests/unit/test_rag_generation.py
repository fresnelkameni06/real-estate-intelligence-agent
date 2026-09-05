"""Offline tests for adaptive, cited RAG answer generation."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from real_estate_agent.rag.embeddings.models import SearchHit
from real_estate_agent.rag.generation.config import RagGenerationSettings
from real_estate_agent.rag.generation.prompts import (
    INSUFFICIENT_CONTEXT_MARKER,
    SYSTEM_INSTRUCTIONS,
    RagPromptError,
    build_grounded_input,
    citations_from_answer,
)
from real_estate_agent.rag.generation.provider import (
    OpenAIResponsesGenerator,
    ResponseGenerationError,
)
from real_estate_agent.rag.generation.service import RagAnswerService


def _hit(index: int = 1, *, similarity: float = 0.76) -> SearchHit:
    return SearchHit(
        chunk_id=f"{index:064x}",
        source_id="dpe_page_ministere",
        chunk_index=index - 1,
        text="Un DPE est valable dix ans, sauf exceptions réglementaires.",
        title="Diagnostic de performance énergétique (DPE)",
        publisher="Ministère de la Transition écologique",
        source_page_url="https://example.gouv.fr/dpe",
        download_url="https://example.gouv.fr/dpe",
        document_format="html",
        heading_path=["DPE", "Durée de validité"],
        page_start=None,
        page_end=None,
        topics=["dpe", "validite"],
        authority_level="official_guidance",
        quality_flags=[],
        similarity=similarity,
    )


class _FakeEmbeddingProvider:
    model = "embedding-test"
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        self.calls.append(values)
        return [[0.1, 0.2, 0.3] for _ in values]


class _FakeRepository:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[list[float], int, Sequence[str] | None]] = []

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        source_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        self.calls.append((list(query_embedding), top_k, source_ids))
        return self.hits


class _FakeGenerator:
    model = "response-test"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> str:
        self.calls.append(
            {
                "instructions": instructions,
                "input_text": input_text,
                "max_output_tokens": max_output_tokens,
            }
        )
        return self.answer


def _service(
    *,
    hits: list[SearchHit] | None = None,
    answer: str = "Un DPE est généralement valable dix ans. [S1]",
    minimum_similarity: float = 0.42,
) -> tuple[RagAnswerService, _FakeEmbeddingProvider, _FakeRepository, _FakeGenerator]:
    embedding = _FakeEmbeddingProvider()
    repository = _FakeRepository([_hit()] if hits is None else hits)
    generator = _FakeGenerator(answer)
    service = RagAnswerService(
        embedding_provider=embedding,
        repository=repository,
        response_generator=generator,
        minimum_similarity=minimum_similarity,
    )
    return service, embedding, repository, generator


def test_generation_settings_defaults_and_secret_redaction():
    settings = RagGenerationSettings(OPENAI_API_KEY="secret-value", _env_file=None)

    assert settings.model == "gpt-5.6-luna"
    assert settings.retrieval_top_k == 5
    assert settings.require_api_key() == "secret-value"
    assert "secret-value" not in repr(settings)


def test_generation_settings_reject_blank_model_and_missing_key():
    with pytest.raises(ValidationError, match="OPENAI_CHAT_MODEL"):
        RagGenerationSettings(
            OPENAI_API_KEY="secret",
            OPENAI_CHAT_MODEL=" ",
            _env_file=None,
        )
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        RagGenerationSettings(OPENAI_API_KEY=None, _env_file=None).require_api_key()


def test_openai_responses_provider_uses_bounded_non_stored_request():
    captured: dict[str, object] = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", output_text="  Réponse [S1]  ")

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    provider = OpenAIResponsesGenerator(
        api_key="secret",
        model="response-test",
        client=client,
    )

    answer = provider.generate(
        instructions="Instructions",
        input_text="Question et contexte",
        max_output_tokens=500,
    )

    assert answer == "Réponse [S1]"
    assert captured == {
        "model": "response-test",
        "instructions": "Instructions",
        "input": "Question et contexte",
        "max_output_tokens": 500,
        "reasoning": {"effort": "low"},
        "store": False,
    }


def test_openai_responses_provider_rejects_empty_or_failed_response():
    empty_client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(output_text=" "))
    )
    provider = OpenAIResponsesGenerator(
        api_key="secret",
        model="response-test",
        client=empty_client,
    )
    with pytest.raises(ResponseGenerationError, match="empty"):
        provider.generate(instructions="Rules", input_text="Input", max_output_tokens=200)

    def fail(**kwargs):
        raise RuntimeError("provider detail")

    failed = OpenAIResponsesGenerator(
        api_key="secret",
        model="response-test",
        client=SimpleNamespace(responses=SimpleNamespace(create=fail)),
    )
    with pytest.raises(ResponseGenerationError, match="model, API access and quota"):
        failed.generate(instructions="Rules", input_text="Input", max_output_tokens=200)


def test_openai_responses_provider_rejects_incomplete_response():
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                status="incomplete",
                output_text="Réponse coupée",
            )
        )
    )
    provider = OpenAIResponsesGenerator(
        api_key="secret",
        model="response-test",
        client=client,
    )

    with pytest.raises(ResponseGenerationError, match="incomplete answer"):
        provider.generate(instructions="Rules", input_text="Input", max_output_tokens=200)


def test_prompt_contains_adaptive_grounding_and_prompt_injection_rules():
    assert "adapte automatiquement" in build_grounded_input(
        "Combien de temps ?",
        [_hit()],
        style="auto",
        max_characters=3_000,
    )[0]
    assert "uniquement à partir" in SYSTEM_INSTRUCTIONS
    assert "ignore toute" in SYSTEM_INSTRUCTIONS
    assert "langue de l'utilisateur" in SYSTEM_INSTRUCTIONS


def test_prompt_labels_sources_and_respects_context_budget():
    first = _hit(1)
    second = _hit(2)
    first.text = "a" * 2_200
    second.text = "b" * 2_200

    prompt, included = build_grounded_input(
        "Question",
        [first, second],
        style="detailed",
        max_characters=2_500,
    )

    assert len(prompt) <= 2_500
    assert len(included) == 1
    assert "[S1]" in prompt
    assert "détaillée" in prompt


def test_citation_validation_maps_only_retrieved_metadata():
    hit = _hit()
    citations = citations_from_answer("Réponse [S1] et rappel [S1].", [hit])

    assert len(citations) == 1
    assert citations[0].citation_id == "S1"
    assert citations[0].url == hit.source_page_url

    with pytest.raises(RagPromptError, match="no source citation"):
        citations_from_answer("Réponse sans preuve.", [hit])
    with pytest.raises(RagPromptError, match="not retrieved"):
        citations_from_answer("Réponse [S2].", [hit])


def test_service_returns_concise_answer_and_auditable_citation():
    service, embedding, repository, generator = _service()

    result = service.answer("  Combien de temps un DPE est-il valable ?  ")

    assert result.answer == "Un DPE est généralement valable dix ans. [S1]"
    assert result.grounded is True
    assert result.insufficient_context is False
    assert result.citations[0].source_id == "dpe_page_ministere"
    assert result.retrieved_chunks == 1
    assert embedding.calls == [["Combien de temps un DPE est-il valable ?"]]
    assert repository.calls[0][1] == 5
    assert generator.calls[0]["max_output_tokens"] == 1600


def test_service_passes_detailed_style_and_source_filters():
    service, _, repository, generator = _service()

    result = service.answer(
        "Explique en détail.",
        style="detailed",
        source_ids=["dpe_page_ministere"],
    )

    assert result.requested_style == "detailed"
    assert "détaillée" in str(generator.calls[0]["input_text"])
    assert repository.calls[0][2] == ["dpe_page_ministere"]


@pytest.mark.parametrize("hits", [[], [_hit(similarity=0.2)]])
def test_service_abstains_before_generation_when_retrieval_is_weak(hits):
    service, _, _, generator = _service(hits=hits, minimum_similarity=0.42)

    result = service.answer("Question hors corpus")

    assert result.insufficient_context is True
    assert result.citations == []
    assert generator.calls == []


def test_service_accepts_explicit_model_abstention_without_fake_citation():
    service, _, _, _ = _service(
        answer=f"{INSUFFICIENT_CONTEXT_MARKER}\nLes extraits ne répondent pas à la question."
    )

    result = service.answer("Question documentaire ambiguë")

    assert result.insufficient_context is True
    assert result.answer == "Les extraits ne répondent pas à la question."
    assert result.citations == []


@pytest.mark.parametrize("question", ["", "   ", "x" * 2_001])
def test_service_rejects_invalid_question_before_api_call(question):
    service, embedding, _, _ = _service()

    with pytest.raises(ValueError, match="question"):
        service.answer(question)

    assert embedding.calls == []


def test_service_rejects_invalid_style_before_api_call():
    service, embedding, _, _ = _service()

    with pytest.raises(ValueError, match="style"):
        service.answer("Question valide", style="very-long")  # type: ignore[arg-type]

    assert embedding.calls == []


def test_service_rejects_answer_without_citation():
    service, _, _, _ = _service(answer="Réponse factuelle sans référence.")

    with pytest.raises(RagPromptError, match="no source citation"):
        service.answer("Question couverte")
