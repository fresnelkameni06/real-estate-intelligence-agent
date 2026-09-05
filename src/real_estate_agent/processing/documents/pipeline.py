"""Deterministic processing pipeline: raw HTML/PDF -> structured JSON.

Verifies the raw file's SHA-256 against the acquisition manifest before
processing, extracts ordered elements, and writes one JSON per source
atomically and idempotently.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from real_estate_agent.ingestion.documents.models import SourceEntry
from real_estate_agent.processing.documents.extractor import extract_html, extract_pdf
from real_estate_agent.processing.documents.models import ProcessedDocument

logger = logging.getLogger(__name__)

DEFAULT_MIN_CHARACTERS = 200


class ProcessingError(RuntimeError):
    """Raised for a controlled processing failure."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """Return the acquisition manifest indexed by source_id."""
    if not manifest_path.exists():
        raise ProcessingError(f"Acquisition manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs = payload.get("documents", [])
    return {d["source_id"]: d for d in docs if "source_id" in d}


def _existing_raw_sha(processed_path: Path) -> str | None:
    """Return the raw_sha256 recorded in an existing processed JSON, if any."""
    if not processed_path.exists():
        return None
    try:
        data = json.loads(processed_path.read_text(encoding="utf-8"))
        return data.get("raw_sha256")
    except (ValueError, OSError):
        return None


def process_source(
    source: SourceEntry,
    raw_dir: Path,
    processed_dir: Path,
    manifest: dict[str, dict[str, Any]],
    *,
    min_characters: int = DEFAULT_MIN_CHARACTERS,
    force: bool = False,
) -> dict[str, Any]:
    """Process one source into a structured JSON document.

    Returns a small result dict: {source_id, status, chars, warnings, error}.
    status in {processed, unchanged, failed}.
    """
    result: dict[str, Any] = {
        "source_id": source.source_id, "status": "failed",
        "chars": 0, "warnings": [], "error": None,
    }

    entry = manifest.get(source.source_id)
    if entry is None:
        result["error"] = "No manifest entry for this source_id."
        return result
    if entry.get("status") == "failed":
        result["error"] = "Manifest entry is marked failed; not processing."
        return result

    ext = "pdf" if source.document_format == "pdf" else "html"
    raw_path = raw_dir / f"{source.source_id}.{ext}"
    if not raw_path.exists():
        result["error"] = f"Raw file missing: {raw_path.name}"
        return result

    # Integrity: raw file SHA-256 must match the manifest's recorded value.
    actual_sha = _sha256(raw_path)
    expected_sha = entry.get("sha256")
    if expected_sha and actual_sha != expected_sha:
        result["error"] = "Checksum mismatch between raw file and manifest."
        return result

    processed_path = processed_dir / f"{source.source_id}.json"

    # Idempotence: unchanged if same raw SHA and not forced.
    if not force and _existing_raw_sha(processed_path) == actual_sha:
        result["status"] = "unchanged"
        return result

    # Extraction.
    try:
        raw_bytes = raw_path.read_bytes()
        if source.document_format == "pdf":
            elements, warnings = extract_pdf(raw_bytes)
        else:
            elements, warnings = extract_html(raw_bytes)
    except ValueError as exc:
        result["error"] = f"Extraction failed: {exc}"
        return result

    total_chars = sum(len(e.text) for e in elements)
    if total_chars < min_characters:
        result["error"] = (
            f"Extracted content too short ({total_chars} < {min_characters} chars)."
        )
        return result

    doc = ProcessedDocument(
        source_id=source.source_id,
        title=source.title,
        publisher=source.publisher,
        source_page_url=source.source_page_url,
        download_url=source.download_url,
        document_format=source.document_format,
        raw_sha256=actual_sha,
        processed_at_utc=_utc_now_iso(),
        elements=elements,
        total_characters=total_chars,
        extraction_warnings=warnings,
    )

    # Atomic write via .part.
    processed_dir.mkdir(parents=True, exist_ok=True)
    part = processed_path.with_suffix(".json.part")
    try:
        part.write_text(
            doc.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        part.replace(processed_path)
    except OSError as exc:
        part.unlink(missing_ok=True)
        result["error"] = f"Write failed: {exc}"
        return result
    finally:
        part.unlink(missing_ok=True)

    result["status"] = "processed"
    result["chars"] = total_chars
    result["warnings"] = warnings
    logger.info("%s: processed (%d chars, %d elements)",
                source.source_id, total_chars, len(elements))
    return result
