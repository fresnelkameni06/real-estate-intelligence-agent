"""Unit tests for the RAG source registry (no network)."""

from __future__ import annotations

import json

import pytest

from real_estate_agent.ingestion.documents.models import SourceEntry
from real_estate_agent.ingestion.documents.registry import (
    RegistryError,
    enabled_sources,
    load_registry,
)


def _valid_entry(**over) -> dict:
    entry = {
        "source_id": "comprendre_mon_dpe",
        "title": "Comprendre mon DPE",
        "publisher": "Ministère",
        "source_page_url": "https://www.ecologie.gouv.fr/x",
        "download_url": "https://www.ecologie.gouv.fr/x.pdf",
        "document_format": "pdf",
        "expected_content_types": ["application/pdf"],
        "authority_level": "official_guidance",
    }
    entry.update(over)
    return entry


def _write(tmp_path, sources):  # noqa: ANN001, ANN202
    p = tmp_path / "rag_sources.json"
    p.write_text(json.dumps({"sources": sources}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_valid_registry_loads(tmp_path):
    p = _write(tmp_path, [_valid_entry()])
    entries = load_registry(p)
    assert len(entries) == 1
    assert entries[0].source_id == "comprendre_mon_dpe"


def test_duplicate_source_id_fails(tmp_path):
    p = _write(tmp_path, [_valid_entry(), _valid_entry()])
    with pytest.raises(RegistryError, match="Duplicate source_id"):
        load_registry(p)


def test_unsafe_source_id_rejected(tmp_path):
    for bad in ("../evil", "a/b", "a\\b", "..", "UPPER"):
        p = _write(tmp_path, [_valid_entry(source_id=bad)])
        with pytest.raises(RegistryError):
            load_registry(p)


def test_missing_required_metadata_fails(tmp_path):
    entry = _valid_entry()
    del entry["download_url"]
    p = _write(tmp_path, [entry])
    with pytest.raises(RegistryError):
        load_registry(p)


def test_non_https_url_rejected(tmp_path):
    p = _write(tmp_path, [_valid_entry(download_url="http://www.ecologie.gouv.fr/x.pdf")])
    with pytest.raises(RegistryError):
        load_registry(p)


def test_empty_registry_fails(tmp_path):
    p = _write(tmp_path, [])
    with pytest.raises(RegistryError, match="no sources"):
        load_registry(p)


def test_missing_file_fails(tmp_path):
    with pytest.raises(RegistryError, match="not found"):
        load_registry(tmp_path / "nope.json")


def test_enabled_filter():
    a = SourceEntry.model_validate(_valid_entry(source_id="a", enabled=True))
    b = SourceEntry.model_validate(_valid_entry(source_id="b", enabled=False))
    assert [s.source_id for s in enabled_sources([a, b])] == ["a"]


def test_real_registry_is_valid():
    # The version-controlled registry must always validate.
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    entries = load_registry(root / "config" / "rag_sources.json")
    assert 6 <= len(entries) <= 8
    ids = [e.source_id for e in entries]
    assert len(ids) == len(set(ids))  # unique
