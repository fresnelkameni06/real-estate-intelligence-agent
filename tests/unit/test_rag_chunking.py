"""Deterministic offline tests for structure-aware RAG chunking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from real_estate_agent.ingestion.documents.models import SourceEntry
from real_estate_agent.processing.documents.models import DocumentElement, ProcessedDocument
from real_estate_agent.rag.chunking.models import ChunkingConfig
from real_estate_agent.rag.chunking.pipeline import (
    load_chunk_manifest,
    process_source,
    read_chunks,
    run_chunking,
)
from real_estate_agent.rag.chunking.splitter import ChunkingError, chunk_document

RAW_SHA = "a" * 64


def _source(source_id: str = "official_source", document_format: str = "html") -> SourceEntry:
    extension = "pdf" if document_format == "pdf" else "html"
    return SourceEntry.model_validate(
        {
            "source_id": source_id,
            "title": f"Title {source_id}",
            "publisher": "Official publisher",
            "source_page_url": f"https://example.gouv.fr/{source_id}",
            "download_url": f"https://example.gouv.fr/{source_id}.{extension}",
            "document_format": document_format,
            "expected_content_types": [
                "application/pdf" if document_format == "pdf" else "text/html"
            ],
            "topics": ["dpe", "reglementation"],
            "language": "fr",
            "jurisdiction": "FR",
            "authority_level": "official_guidance",
            "is_normative": False,
        }
    )


def _document(
    elements: list[DocumentElement],
    source_id: str = "official_source",
    document_format: str = "html",
) -> ProcessedDocument:
    return ProcessedDocument(
        source_id=source_id,
        title=f"Title {source_id}",
        publisher="Official publisher",
        source_page_url=f"https://example.gouv.fr/{source_id}",
        download_url=f"https://example.gouv.fr/{source_id}",
        document_format=document_format,
        raw_sha256=RAW_SHA,
        processed_at_utc="2026-09-05T00:00:00+00:00",
        elements=elements,
        total_characters=sum(len(element.text) for element in elements),
    )


def _paragraphs(*texts: str) -> list[DocumentElement]:
    return [
        DocumentElement(order=index, kind="paragraph", text=text)
        for index, text in enumerate(texts)
    ]


@pytest.mark.parametrize(
    "values",
    [
        {"minimum_chunk_characters": 1400},
        {"target_characters": 1900, "maximum_characters": 1800},
        {"overlap_characters": 1400},
    ],
)
def test_configuration_rejects_invalid_limit_relationships(values):
    with pytest.raises(ValidationError):
        ChunkingConfig(**values)


def test_heading_hierarchy_is_propagated_to_text_and_metadata():
    elements = [
        DocumentElement(order=0, kind="heading", text="DPE", heading_level=1),
        DocumentElement(order=1, kind="heading", text="Location", heading_level=2),
        DocumentElement(
            order=2,
            kind="paragraph",
            text="Les règles de location sont décrites dans cette section officielle.",
        ),
    ]
    chunks = chunk_document(_document(elements), _source(), ChunkingConfig())

    assert chunks[0].heading_path == ["DPE", "Location"]
    assert chunks[0].text.startswith("DPE > Location\n\n")


def test_pdf_page_numbers_are_never_misattributed():
    elements = [
        DocumentElement(order=0, kind="page", text="Contenu officiel page une. " * 15,
                        page_number=1),
        DocumentElement(order=1, kind="page", text="Contenu officiel page deux. " * 15,
                        page_number=2),
    ]
    chunks = chunk_document(
        _document(elements, document_format="pdf"),
        _source(document_format="pdf"),
        ChunkingConfig(target_characters=300, maximum_characters=450,
                       overlap_characters=50, minimum_chunk_characters=40),
    )

    assert {chunk.page_start for chunk in chunks} == {1, 2}
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)


def test_oversized_text_respects_maximum_and_uses_bounded_overlap():
    text = " ".join(f"mot{i}" for i in range(500))
    config = ChunkingConfig(
        target_characters=400,
        maximum_characters=500,
        overlap_characters=60,
        minimum_chunk_characters=30,
    )
    chunks = chunk_document(_document(_paragraphs(text)), _source(), config)

    assert len(chunks) > 2
    assert all(chunk.character_count <= config.maximum_characters for chunk in chunks)
    first_tail = chunks[0].text.split()[-3:]
    assert all(word in chunks[1].text.split()[:12] for word in first_tail)


def test_pathological_token_is_kept_and_flagged():
    token = "x" * 600
    chunks = chunk_document(
        _document(_paragraphs(token)),
        _source(),
        ChunkingConfig(target_characters=300, maximum_characters=400,
                       overlap_characters=20, minimum_chunk_characters=10),
    )

    assert chunks[0].text == token
    assert "pathological_token" in chunks[0].quality_flags


def test_short_document_is_chunked_with_visible_quality_warning():
    chunks = chunk_document(
        _document(_paragraphs("Description DVF officielle mais limitée.")),
        _source(),
        ChunkingConfig(short_document_warning_threshold=1000),
    )

    assert len(chunks) == 1
    assert "limited_source_content" in chunks[0].quality_flags


def test_small_final_fragment_is_merged_when_compatible():
    main = "Information officielle détaillée. " * 14
    elements = _paragraphs(main, "Complément utile.")
    chunks = chunk_document(
        _document(elements),
        _source(),
        ChunkingConfig(target_characters=350, maximum_characters=700,
                       overlap_characters=0, minimum_chunk_characters=120),
    )

    assert chunks[-1].text.endswith("Complément utile.")
    assert chunks[-1].character_count >= 120


def test_tiny_html_preamble_is_merged_into_first_named_section():
    elements = [
        DocumentElement(order=0, kind="paragraph", text="Publié le 5 septembre."),
        DocumentElement(order=1, kind="heading", text="Audit énergétique", heading_level=1),
        DocumentElement(
            order=2,
            kind="paragraph",
            text="Cette section présente les obligations réglementaires applicables.",
        ),
    ]
    chunks = chunk_document(
        _document(elements),
        _source(),
        ChunkingConfig(minimum_chunk_characters=120),
    )

    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Audit énergétique"]
    assert "Publié le 5 septembre." in chunks[0].text
    assert "obligations réglementaires" in chunks[0].text


def test_chunk_ids_and_hashes_are_stable_and_unique():
    document = _document(_paragraphs("Texte officiel long et fiable. " * 100))
    config = ChunkingConfig(target_characters=400, maximum_characters=500,
                            overlap_characters=50, minimum_chunk_characters=20)
    first = chunk_document(document, _source(), config)
    second = chunk_document(document, _source(), config)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert [chunk.content_sha256 for chunk in first] == [
        chunk.content_sha256 for chunk in second
    ]
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert len({chunk.content_sha256 for chunk in first}) == len(first)


def test_non_contiguous_processed_elements_are_rejected():
    elements = [DocumentElement(order=3, kind="paragraph", text="Contenu officiel.")]
    with pytest.raises(ChunkingError, match="contiguous"):
        chunk_document(_document(elements), _source(), ChunkingConfig())


def _write_processed(directory: Path, source: SourceEntry, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    document = _document(_paragraphs(text), source.source_id, source.document_format)
    path = directory / f"{source.source_id}.json"
    path.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def test_pipeline_writes_valid_jsonl_manifest_and_no_part_files(tmp_path):
    processed = tmp_path / "documents"
    output = tmp_path / "chunks"
    source = _source()
    _write_processed(processed, source, "Règle énergétique officielle. " * 100)

    results, manifest = run_chunking([source], processed, output, ChunkingConfig())

    chunks = read_chunks(output / "official_source.jsonl")
    assert results[0]["status"] == "chunked"
    assert manifest.total_sources == 1
    assert manifest.total_chunks == len(chunks)
    assert load_chunk_manifest(output / "manifest.json") is not None
    assert list(output.glob("*.part")) == []
    for line in (output / "official_source.jsonl").read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["source_id"] == source.source_id


def test_pipeline_is_idempotent_and_force_regenerates(tmp_path):
    processed = tmp_path / "documents"
    output = tmp_path / "chunks"
    source = _source()
    _write_processed(processed, source, "Contenu officiel contrôlé. " * 80)

    first, _ = run_chunking([source], processed, output, ChunkingConfig())
    chunk_path = output / "official_source.jsonl"
    first_mtime = chunk_path.stat().st_mtime_ns
    second, _ = run_chunking([source], processed, output, ChunkingConfig())
    second_mtime = chunk_path.stat().st_mtime_ns
    forced, _ = run_chunking([source], processed, output, ChunkingConfig(), force=True)

    assert first[0]["status"] == "chunked"
    assert second[0]["status"] == "unchanged"
    assert second_mtime == first_mtime
    assert forced[0]["status"] == "updated"


def test_targeted_run_preserves_other_manifest_sources(tmp_path):
    processed = tmp_path / "documents"
    output = tmp_path / "chunks"
    first_source = _source("source_one")
    second_source = _source("source_two")
    _write_processed(processed, first_source, "Premier document officiel. " * 50)
    _write_processed(processed, second_source, "Deuxième document officiel. " * 50)
    config = ChunkingConfig()
    run_chunking([first_source, second_source], processed, output, config)

    results, manifest = run_chunking([first_source], processed, output, config)

    assert results[0]["status"] == "unchanged"
    assert {entry.source_id for entry in manifest.sources} == {"source_one", "source_two"}
    assert manifest.total_sources == 2


def test_invalid_processed_document_returns_controlled_failure(tmp_path):
    processed = tmp_path / "documents"
    processed.mkdir()
    (processed / "official_source.json").write_text("{not-json", encoding="utf-8")

    result, entry = process_source(
        _source(), processed, tmp_path / "chunks", ChunkingConfig()
    )

    assert result["status"] == "failed"
    assert entry.status == "failed"
    assert "Invalid processed document" in (entry.error or "")


def test_read_chunks_rejects_mixed_sources(tmp_path):
    processed = tmp_path / "documents"
    output = tmp_path / "chunks"
    source = _source()
    _write_processed(processed, source, "Information officielle. " * 80)
    run_chunking([source], processed, output, ChunkingConfig())
    path = output / "official_source.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["source_id"] = "another_source"
    path.write_text(json.dumps(record) + "\n" + "\n".join(lines[1:]) + "\n", encoding="utf-8")

    with pytest.raises(ChunkingError, match="Multiple sources"):
        read_chunks(path)
