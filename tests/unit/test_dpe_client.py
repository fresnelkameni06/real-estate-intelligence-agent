"""Unit tests for the DPE API client, using mocked HTTP responses only.

No real ADEME API calls. httpx is driven by a MockTransport.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from real_estate_agent.ingestion.dpe import client as dpe_client


def _resp(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _client_from(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="https://data.ademe.fr")


# --------------------------------------------------------------------------- #
# Multi-page retrieval
# --------------------------------------------------------------------------- #

def test_multi_page_retrieval_follows_next():
    pages = [
        {"results": [{"numero_dpe": "A"}], "next": "https://x/next1", "total": 3},
        {"results": [{"numero_dpe": "B"}], "next": "https://x/next2"},
        {"results": [{"numero_dpe": "C"}]},  # no next -> stop
    ]
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = calls["i"]
        calls["i"] += 1
        return _resp(pages[i])

    client = _client_from(handler)
    collected = []
    for page in dpe_client.iter_pages(client, sleep=lambda s: None):
        collected.extend(page)
    assert [r["numero_dpe"] for r in collected] == ["A", "B", "C"]


# --------------------------------------------------------------------------- #
# Retry after 429 and after transient 5xx
# --------------------------------------------------------------------------- #

def test_retry_after_429_then_success():
    seq = [429, 200]
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        status = seq[calls["i"]]
        calls["i"] += 1
        if status == 200:
            return _resp({"results": [], "total": 0})
        return httpx.Response(429)

    client = _client_from(handler)
    resp = dpe_client._get_with_retry(client, "https://x/lines", {}, sleep=lambda s: None)
    assert resp.status_code == 200
    assert calls["i"] == 2


def test_retry_after_503_then_success():
    seq = [503, 503, 200]
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        status = seq[calls["i"]]
        calls["i"] += 1
        if status == 200:
            return _resp({"results": []})
        return httpx.Response(status)

    client = _client_from(handler)
    resp = dpe_client._get_with_retry(client, "https://x/lines", {}, sleep=lambda s: None)
    assert resp.status_code == 200
    assert calls["i"] == 3


# --------------------------------------------------------------------------- #
# Malformed response
# --------------------------------------------------------------------------- #

def test_malformed_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return _resp({"unexpected": True})  # no 'results'

    client = _client_from(handler)
    with pytest.raises(ValueError):
        list(dpe_client.iter_pages(client, sleep=lambda s: None))


# --------------------------------------------------------------------------- #
# Pagination with no progress (repeated cursor)
# --------------------------------------------------------------------------- #

def test_pagination_no_progress_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        # Always returns the same 'next' -> no progress.
        return _resp({"results": [{"numero_dpe": "X"}], "next": "https://x/same"})

    client = _client_from(handler)
    with pytest.raises(RuntimeError, match="no progress"):
        list(dpe_client.iter_pages(client, sleep=lambda s: None))


# --------------------------------------------------------------------------- #
# Snapshot reuse / corruption / --refresh
# --------------------------------------------------------------------------- #

def _write_snapshot(raw_dir: Path, rows: list[dict]) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload = {"dataset_id": "dpe03existant", "filter": 'code_departement_ban:"75"',
               "selected_fields": dpe_client.APPROVED_FIELDS, "results": rows}
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    (raw_dir / "dpe_75_snapshot.json").write_bytes(data)
    manifest = {
        "dataset_id": "dpe03existant", "retrieved_rows": len(rows),
        "sha256": dpe_client._sha256_bytes(data), "complete": True,
        "expected_total": len(rows), "page_count": 1,
    }
    (raw_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_valid_snapshot_is_reused(tmp_path):
    raw = tmp_path / "dpe"
    _write_snapshot(raw, [{"numero_dpe": "A"}])
    assert dpe_client.snapshot_is_valid(raw) is True

    # acquire without refresh must NOT call the API (no client given, but reuse
    # path returns before any network use).
    manifest = dpe_client.acquire_snapshot(raw, refresh=False)
    assert manifest["retrieved_rows"] == 1


def test_corrupted_snapshot_detected(tmp_path):
    raw = tmp_path / "dpe"
    _write_snapshot(raw, [{"numero_dpe": "A"}])
    # Corrupt the snapshot so checksum no longer matches the manifest.
    (raw / "dpe_75_snapshot.json").write_bytes(b'{"results": [], "corrupted": true}')
    assert dpe_client.snapshot_is_valid(raw) is False


def test_refresh_forces_new_snapshot(tmp_path):
    raw = tmp_path / "dpe"
    _write_snapshot(raw, [{"numero_dpe": "OLD"}])

    pages = [{"results": [{"numero_dpe": "NEW"}], "total": 1}]
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        # First call is fetch_total (size=0), second is the page.
        if calls["i"] == 0:
            calls["i"] += 1
            return _resp({"total": 1})
        return _resp(pages[0])

    client = _client_from(handler)
    manifest = dpe_client.acquire_snapshot(
        raw, refresh=True, sleep=lambda s: None, client=client
    )
    assert manifest["retrieved_rows"] == 1
    snap = json.loads((raw / "dpe_75_snapshot.json").read_text(encoding="utf-8"))
    assert snap["results"][0]["numero_dpe"] == "NEW"
