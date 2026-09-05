"""Load and validate the version-controlled RAG source registry.

Fails clearly on duplicate source_id values, missing required metadata or
malformed entries. Never silently skips a bad entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from real_estate_agent.ingestion.documents.models import SourceEntry


class RegistryError(RuntimeError):
    """Raised when the source registry is invalid."""


def load_registry(path: Path) -> list[SourceEntry]:
    """Load and validate all source entries from a registry JSON file."""
    if not path.exists():
        raise RegistryError(f"Registry file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"Registry is not valid JSON: {exc}") from exc

    entries_raw = raw.get("sources") if isinstance(raw, dict) else raw
    if not isinstance(entries_raw, list):
        raise RegistryError("Registry must contain a list under key 'sources'.")

    entries: list[SourceEntry] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(entries_raw):
        try:
            entry = SourceEntry.model_validate(item)
        except ValidationError as exc:
            raise RegistryError(f"Invalid source entry at index {i}: {exc}") from exc
        if entry.source_id in seen_ids:
            raise RegistryError(f"Duplicate source_id: '{entry.source_id}'")
        seen_ids.add(entry.source_id)
        entries.append(entry)

    if not entries:
        raise RegistryError("Registry contains no sources.")
    return entries


def enabled_sources(entries: list[SourceEntry]) -> list[SourceEntry]:
    """Return only the enabled sources."""
    return [e for e in entries if e.enabled]
