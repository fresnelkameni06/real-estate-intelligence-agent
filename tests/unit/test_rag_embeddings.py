"""Offline tests for OpenAI embeddings orchestration and pgvector metadata."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from real_estate_agent.database.models import RagDocumentChunk
from real_estate_agent.rag.chunking.models import DocumentChunk
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
from real_estate_agent.rag.embeddings.repository import (
    EmbeddedChunk,
    ExistingEmbeddingState,
)

SHA = "a" * 64


def _chunk(index: int, source_id: str = "official_source") -> DocumentChunk:
    text = f"Texte réglementaire officiel numéro {index}."
    return DocumentChunk(
        chunking_version="semantic-char-v1",
        chunk_id=f"{index + 1:064x}",
        source_id=source_id,
        chunk_index=index,
        text=text,
        character_count=len(text),
        word_count=len(text.split()),
        content_sha256=f"{index + 101:064x}",
        title="Document officiel",
        publisher="Ministère",
        source_page_url="https://example.gouv.fr/document",
        download_url="https://example.gouv.fr/document",
        document_format="html",
        raw_sha256=SHA,
        heading_path=["DPE", "Location"],
        topics=["dpe", "location"],
        language="fr",
        jurisdiction="FR",
        authority_level="official_guidance",
        is_normative=False,
    )


class _FakeProvider:
    model = "text-embedding-test"
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        self.calls.append(values)
        return [[float(index), 0.5, -0.5] for index, _ in enumerate(values)]


class _FakeRepository:
    def __init__(self) -> None:
        self.states: dict[str, ExistingEmbeddingState] = {}
        self.synchronize_calls = 0
        self.last_embedded: list[EmbeddedChunk] = []
        self.stale_ids: set[str] = set()

    def existing_states(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, ExistingEmbeddingState]:
        return {
            chunk_id: self.states[chunk_id]
            for chunk_id in chunk_ids
            if chunk_id in self.states
        }

    def synchronize(
        self,
        embedded_chunks: Sequence[EmbeddedChunk],
        *,
        selected_source_ids: set[str],
        current_chunk_ids: set[str],
    ) -> int:
        self.synchronize_calls += 1
        self.last_embedded = list(embedded_chunks)
        deleted = len(self.stale_ids)
        self.stale_ids.clear()
        for item in embedded_chunks:
            self.states[item.chunk.chunk_id] = ExistingEmbeddingState(
                chunk_id=item.chunk.chunk_id,
                content_sha256=item.chunk.content_sha256,
                embedding_model=item.model,
                embedding_dimensions=item.dimensions,
            )
        assert selected_source_ids
        assert current_chunk_ids
        return deleted


def test_embedding_settings_defaults_and_secret_is_redacted():
    settings = EmbeddingSettings(OPENAI_API_KEY="secret-test-value", _env_file=None)

    assert settings.model == "text-embedding-3-small"
    assert settings.dimensions == 1536
    assert settings.batch_size == 64
    assert settings.require_api_key() == "secret-test-value"
    assert "secret-test-value" not in repr(settings)


def test_embedding_settings_require_key_and_fixed_database_dimensions():
    missing = EmbeddingSettings(OPENAI_API_KEY=None, _env_file=None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        missing.require_api_key()

    with pytest.raises(ValidationError, match=r"vector\(1536\)"):
        EmbeddingSettings(
            OPENAI_API_KEY="secret",
            OPENAI_EMBEDDING_DIMENSIONS=1024,
            _env_file=None,
        )


def test_database_model_uses_vector_1536_and_traceable_fields():
    table = RagDocumentChunk.__table__

    assert table.c.embedding.type.dim == 1536
    assert table.c.chunk_id.primary_key
    assert table.c.source_page_url.nullable is False
    assert table.c.embedding_model.nullable is False


def test_openai_provider_preserves_response_index_order():
    response = SimpleNamespace(
        data=[
            SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
            SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
        ]
    )
    embeddings = SimpleNamespace(create=lambda **kwargs: response)
    client = SimpleNamespace(embeddings=embeddings)
    provider = OpenAIEmbeddingProvider(
        api_key="secret",
        model="embedding-test",
        dimensions=3,
        client=client,
    )

    vectors = provider.embed(["premier", "second"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([SimpleNamespace(index=0, embedding=[0.1])], "Expected 3 dimensions"),
        ([SimpleNamespace(index=1, embedding=[0.1, 0.2, 0.3])], "unexpected result"),
        ([SimpleNamespace(index=0, embedding=[0.1, float("nan"), 0.3])], "non-finite"),
    ],
)
def test_openai_provider_rejects_invalid_responses(data, message):
    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(data=data))
    )
    provider = OpenAIEmbeddingProvider(
        api_key="secret",
        model="embedding-test",
        dimensions=3,
        client=client,
    )

    with pytest.raises(EmbeddingProviderError, match=message):
        provider.embed(["texte"])


def test_openai_provider_rejects_blank_text_without_api_call():
    provider = OpenAIEmbeddingProvider(
        api_key="secret",
        model="embedding-test",
        dimensions=3,
        client=SimpleNamespace(),
    )
    with pytest.raises(EmbeddingProviderError, match="Blank"):
        provider.embed([" "])


def _write_chunks(path: Path, chunks: Sequence[DocumentChunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n",
        encoding="utf-8",
    )


def test_load_chunk_corpus_selects_sources_and_rejects_missing(tmp_path):
    _write_chunks(tmp_path / "source_a.jsonl", [_chunk(0, "source_a")])
    _write_chunks(tmp_path / "source_b.jsonl", [_chunk(0, "source_b")])

    selected = load_chunk_corpus(tmp_path, source_ids=["source_b"])
    assert [chunk.source_id for chunk in selected] == ["source_b"]

    with pytest.raises(EmbeddingPipelineError, match="missing_source"):
        load_chunk_corpus(tmp_path, source_ids=["missing_source"])


def test_load_chunk_corpus_rejects_duplicate_ids_across_sources(tmp_path):
    first = _chunk(0, "source_a")
    second_payload = _chunk(0, "source_b").model_dump()
    second_payload["chunk_id"] = first.chunk_id
    second = DocumentChunk.model_validate(second_payload)
    _write_chunks(tmp_path / "source_a.jsonl", [first])
    _write_chunks(tmp_path / "source_b.jsonl", [second])

    with pytest.raises(EmbeddingPipelineError, match="duplicate chunk IDs"):
        load_chunk_corpus(tmp_path)


def test_pipeline_batches_first_run_and_second_run_is_api_noop():
    chunks = [_chunk(index) for index in range(5)]
    provider = _FakeProvider()
    repository = _FakeRepository()

    first = run_embedding_index(chunks, provider, repository, batch_size=2)
    second = run_embedding_index(chunks, provider, repository, batch_size=2)

    assert [len(call) for call in provider.calls] == [2, 2, 1]
    assert first.embedded_chunks == 5
    assert first.unchanged_chunks == 0
    assert second.embedded_chunks == 0
    assert second.unchanged_chunks == 5
    assert repository.synchronize_calls == 2


def test_pipeline_force_and_model_change_regenerate_embeddings():
    chunks = [_chunk(0)]
    provider = _FakeProvider()
    repository = _FakeRepository()
    run_embedding_index(chunks, provider, repository)

    forced = run_embedding_index(chunks, provider, repository, force=True)
    provider.model = "another-embedding-model"
    changed_model = run_embedding_index(chunks, provider, repository)

    assert forced.embedded_chunks == 1
    assert changed_model.embedded_chunks == 1
    assert len(provider.calls) == 3


def test_pipeline_reports_stale_deletion():
    provider = _FakeProvider()
    repository = _FakeRepository()
    repository.stale_ids.add("old-id")

    result = run_embedding_index([_chunk(0)], provider, repository)

    assert result.deleted_stale_chunks == 1


def test_pipeline_rejects_empty_or_duplicate_corpus():
    provider = _FakeProvider()
    repository = _FakeRepository()
    with pytest.raises(EmbeddingPipelineError, match="empty"):
        run_embedding_index([], provider, repository)

    duplicate = _chunk(0)
    with pytest.raises(EmbeddingPipelineError, match="duplicate"):
        run_embedding_index([duplicate, duplicate], provider, repository)


def test_jsonl_fixture_is_plain_json_not_secret_bearing(tmp_path):
    path = tmp_path / "source.jsonl"
    _write_chunks(path, [_chunk(0)])
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    assert payload["source_page_url"].startswith("https://")
    assert "api_key" not in payload
