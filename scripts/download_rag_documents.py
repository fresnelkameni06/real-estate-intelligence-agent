"""Download approved RAG documents declared in config/rag_sources.json."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from real_estate_agent.ingestion.documents.downloader import (
    DEFAULT_MAX_SIZE_MB,
    download_source,
)
from real_estate_agent.ingestion.documents.models import ManifestEntry
from real_estate_agent.ingestion.documents.registry import (
    RegistryError,
    enabled_sources,
    load_registry,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_rag")

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "rag_sources.json"
DEST_DIR = REPO_ROOT / "data" / "raw" / "documents"
MANIFEST_PATH = DEST_DIR / "manifest.json"


def _load_existing_manifest() -> dict[str, ManifestEntry]:
    """Load the existing manifest before a targeted update."""
    if not MANIFEST_PATH.exists():
        return {}

    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            raise ValueError("Manifest root must be a JSON object.")

        documents = payload.get("documents")

        if not isinstance(documents, list):
            raise ValueError("Manifest must contain a 'documents' list.")

        entries: dict[str, ManifestEntry] = {}

        for index, item in enumerate(documents):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Manifest entry at index {index} must be an object."
                )

            entry = ManifestEntry.model_validate(item)
            entries[entry.source_id] = entry

        return entries

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Existing manifest is invalid: {exc}") from exc


def _write_manifest(
    entries: list[ManifestEntry],
    *,
    preserve_existing: bool = False,
) -> None:
    """Write the manifest atomically.

    During a targeted download, existing source entries are preserved and only
    the selected source is updated.
    """
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    merged_entries = (
        _load_existing_manifest()
        if preserve_existing
        else {}
    )

    for entry in entries:
        merged_entries[entry.source_id] = entry

    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "documents": [
            entry.model_dump()
            for entry in merged_entries.values()
        ],
    }

    temporary_path = MANIFEST_PATH.with_suffix(
        MANIFEST_PATH.suffix + ".part"
    )

    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(MANIFEST_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download approved RAG documents."
    )
    parser.add_argument(
        "--source-id",
        help="Download only this source_id.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the local file even when its checksum is unchanged.",
    )
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=DEFAULT_MAX_SIZE_MB,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and list sources without downloading.",
    )

    args = parser.parse_args(argv)

    if args.max_size_mb <= 0:
        logger.error("--max-size-mb must be greater than zero.")
        return 2

    try:
        registry = load_registry(REGISTRY_PATH)
    except RegistryError as exc:
        logger.error("Registry validation failed: %s", exc)
        return 2

    sources = enabled_sources(registry)

    if args.source_id:
        sources = [
            source
            for source in sources
            if source.source_id == args.source_id
        ]

        if not sources:
            logger.error(
                "No enabled source with source_id '%s'.",
                args.source_id,
            )
            return 2

    if args.dry_run:
        logger.info(
            "Dry run — %d planned source(s):",
            len(sources),
        )

        for source in sources:
            logger.info(
                "  %s [%s] -> %s",
                source.source_id,
                source.document_format,
                source.download_url,
            )

        return 0

    entries: list[ManifestEntry] = []

    for source in sources:
        entry = download_source(
            source,
            DEST_DIR,
            max_size_mb=args.max_size_mb,
            force=args.force,
        )
        entries.append(entry)

    try:
        _write_manifest(
            entries,
            preserve_existing=args.source_id is not None,
        )
    except (OSError, RuntimeError) as exc:
        logger.error("Manifest write failed: %s", exc)
        return 2

    succeeded = [
        entry
        for entry in entries
        if entry.status != "failed"
    ]
    failed = [
        entry
        for entry in entries
        if entry.status == "failed"
    ]

    logger.info(
        "Done: %d ok, %d failed. Manifest -> %s",
        len(succeeded),
        len(failed),
        MANIFEST_PATH,
    )

    for entry in failed:
        logger.warning(
            "FAILED %s: %s",
            entry.source_id,
            entry.error,
        )

    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
