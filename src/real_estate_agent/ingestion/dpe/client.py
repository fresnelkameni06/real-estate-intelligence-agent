"""Paginated ADEME DPE API client for the Paris (department 75) snapshot.

Retrieves the complete filtered Paris dataset via cursor pagination, with bounded
exponential backoff on HTTP 429 / transient 5xx, no-progress detection, atomic
snapshot writing, and manifest-driven idempotence.

Only the approved (non-address) fields are requested. Individual records are
never logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DATASET_ID = "dpe03existant"
BASE = "https://data.ademe.fr/data-fair/api/v1/datasets"
META_URL = f"{BASE}/{DATASET_ID}"
LINES_URL = f"{BASE}/{DATASET_ID}/lines"

PARIS_FILTER = 'code_departement_ban:"75"'

# Approved fields only (verified against the real schema). No address fields.
APPROVED_FIELDS = [
    "_id",
    "numero_dpe",
    "date_etablissement_dpe",
    "date_reception_dpe",
    "date_fin_validite_dpe",
    "etiquette_dpe",
    "etiquette_ges",
    "conso_5_usages_par_m2_ep",
    "emission_ges_5_usages_par_m2",
    "surface_habitable_logement",
    "type_batiment",
    "periode_construction",
    "code_postal_ban",
    "code_insee_ban",
    "code_departement_ban",
    "_geopoint",
]

PAGE_SIZE = 10000
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 60.0
MAX_RETRIES = 5
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0

RETRY_STATUS = {429, 500, 502, 503, 504}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sleep_backoff(attempt: int, sleep: Callable[[float], None]) -> None:
    """Bounded exponential backoff (attempt starts at 1)."""
    delay = min(BACKOFF_CAP, BACKOFF_BASE ** attempt)
    sleep(delay)


def _get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET with bounded exponential backoff on 429 / transient 5xx."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.get(url, params=params)
            if resp.status_code in RETRY_STATUS:
                logger.warning("DPE: HTTP %s (attempt %d/%d), backing off",
                               resp.status_code, attempt, MAX_RETRIES)
                _sleep_backoff(attempt, sleep)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("DPE: transport error (attempt %d/%d): %s",
                           attempt, MAX_RETRIES, exc)
            _sleep_backoff(attempt, sleep)
    raise RuntimeError(f"DPE: exhausted retries for {url}: {last_exc}")


def fetch_total(client: httpx.Client) -> int | None:
    """Return the API-announced total for the Paris filter, if provided."""
    params = {"qs": PARIS_FILTER, "size": 0}
    resp = _get_with_retry(client, LINES_URL, params)
    payload = resp.json()
    return payload.get("total")


def iter_pages(
    client: httpx.Client,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Yield successive result pages, following the API ``next`` cursor.

    Detects no-progress (a ``next`` that does not advance) and stops with an
    error rather than looping forever.
    """
    params: dict[str, Any] = {
        "qs": PARIS_FILTER,
        "size": PAGE_SIZE,
        "select": ",".join(APPROVED_FIELDS),
    }
    url = LINES_URL
    seen_nexts: set[str] = set()
    use_params: dict[str, Any] | None = params

    while True:
        resp = _get_with_retry(client, url, use_params, sleep)
        payload = resp.json()
        if "results" not in payload:
            raise ValueError("DPE: malformed API response (no 'results')")
        results = payload["results"]
        yield results

        next_url = payload.get("next")
        if not next_url:
            return
        if next_url in seen_nexts:
            raise RuntimeError("DPE: pagination made no progress (repeated cursor)")
        seen_nexts.add(next_url)
        # The API returns a fully-formed next URL; follow it with no extra params.
        url = next_url
        use_params = None


def _snapshot_paths(raw_dir: Path) -> tuple[Path, Path]:
    return raw_dir / "dpe_75_snapshot.json", raw_dir / "manifest.json"


def snapshot_is_valid(raw_dir: Path) -> bool:
    """Return True if a complete snapshot and matching manifest already exist."""
    snap, manifest_path = _snapshot_paths(raw_dir)
    if not snap.exists() or not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data = snap.read_bytes()
        if _sha256_bytes(data) != manifest.get("sha256"):
            return False
        payload = json.loads(data.decode("utf-8"))
        return (
            manifest.get("complete") is True
            and len(payload.get("results", [])) == manifest.get("retrieved_rows")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def acquire_snapshot(
    raw_dir: Path,
    refresh: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Acquire the complete Paris DPE snapshot, or reuse a valid local one.

    Writes ``dpe_75_snapshot.json`` atomically and a ``manifest.json`` beside it.
    Returns the manifest.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    snap, manifest_path = _snapshot_paths(raw_dir)

    if not refresh and snapshot_is_valid(raw_dir):
        logger.info("DPE: reusing valid local snapshot (no API call)")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    owns_client = client is None
    if client is None:
        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        client = httpx.Client(timeout=timeout, follow_redirects=True)

    started = _utc_now_iso()
    all_rows: list[dict[str, Any]] = []
    page_count = 0
    try:
        expected_total = fetch_total(client)
        logger.info("DPE: expected total (Paris) = %s", expected_total)
        for results in iter_pages(client, sleep):
            page_count += 1
            all_rows.extend(results)
            logger.info("DPE: page %d, cumulative rows=%d", page_count, len(all_rows))
    finally:
        if owns_client:
            client.close()

    finished = _utc_now_iso()
    payload = {
        "dataset_id": DATASET_ID,
        "filter": PARIS_FILTER,
        "selected_fields": APPROVED_FIELDS,
        "results": all_rows,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    # Atomic write via .part
    part = snap.with_suffix(snap.suffix + ".part")
    try:
        part.write_bytes(data)
        part.replace(snap)
    except OSError:
        part.unlink(missing_ok=True)
        raise

    manifest = {
        "dataset_id": DATASET_ID,
        "filter": PARIS_FILTER,
        "selected_fields": APPROVED_FIELDS,
        "extraction_started_utc": started,
        "extraction_finished_utc": finished,
        "expected_total": expected_total,
        "retrieved_rows": len(all_rows),
        "page_count": page_count,
        "sha256": _sha256_bytes(data),
        "complete": (expected_total is None) or (len(all_rows) >= expected_total),
        "snapshot_path": str(snap.name),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("DPE: snapshot written (%d rows, %d pages) -> %s",
                len(all_rows), page_count, snap)
    return manifest
