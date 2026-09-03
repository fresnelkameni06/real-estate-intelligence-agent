"""Idempotent acquisition of geo-DVF department-75 files (2021-2025).

The geo-DVF source is published under a moving ``latest`` URL, so the compressed
file for a given year can change between runs. Acquisition is therefore
manifest-driven rather than hardcoded-checksum-driven:

* the first time a year is fetched, its SHA-256 is recorded in the manifest;
* on later runs a local file is reused only when it exists, is a readable gzip,
  and its checksum matches the manifest entry;
* a raw file that is already valid is never modified silently.

Download is streamed to a temporary ``.part`` file, validated, then atomically
renamed to ``75.csv.gz`` so a partial download can never masquerade as complete.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DVF_YEARS = (2021, 2022, 2023, 2024, 2025)
DVF_URL_TEMPLATE = (
    "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/departements/75.csv.gz"
)

CONNECT_TIMEOUT = 15.0
DOWNLOAD_TIMEOUT = 180.0


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    """Compute the SHA-256 checksum of a file, streaming to bound memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_readable_gzip(path: Path) -> bool:
    """Return True if the file exists and can be opened/read as gzip."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rb") as fh:
            fh.read(1024)  # read a small chunk to confirm it decompresses
        return True
    except (OSError, EOFError, gzip.BadGzipFile):
        return False


def dvf_url(year: int) -> str:
    """Build the exact department-75 URL for a given year."""
    return DVF_URL_TEMPLATE.format(year=year)


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load the acquisition manifest, or return an empty structure."""
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"files": {}}


def save_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest as UTF-8 JSON."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _download_to_file(url: str, dest: Path, client: httpx.Client) -> dict[str, Any]:
    """Stream ``url`` into ``dest`` via a temporary ``.part`` file, atomically.

    Returns HTTP-side metadata (content length, last-modified).
    """
    part = dest.with_suffix(dest.suffix + ".part")
    if part.exists():
        part.unlink()

    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        content_length = resp.headers.get("content-length")
        last_modified = resp.headers.get("last-modified")
        with part.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                fh.write(chunk)

    # Validate before committing: non-empty and readable as gzip.
    if not _is_readable_gzip(part):
        part.unlink(missing_ok=True)
        raise OSError(f"Downloaded file failed gzip validation: {url}")

    # Atomic rename (same filesystem) so a partial file never becomes 75.csv.gz.
    part.replace(dest)
    return {"content_length": content_length, "last_modified": last_modified}


def acquire_year(
    year: int,
    raw_root: Path,
    manifest: dict[str, Any],
    client: httpx.Client,
) -> dict[str, Any]:
    """Acquire the department-75 file for one year, reusing a valid local copy.

    Updates ``manifest`` in place and returns the per-year record.
    """
    url = dvf_url(year)
    year_dir = raw_root / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    dest = year_dir / "75.csv.gz"

    manifest_entry = manifest.get("files", {}).get(str(year))
    reused = False
    http_meta: dict[str, Any] = {}

    if (
        manifest_entry is not None
        and _is_readable_gzip(dest)
        and _sha256(dest) == manifest_entry.get("sha256")
    ):
        logger.info("DVF %s: reusing valid local file (manifest checksum match)", year)
        reused = True
    else:
        logger.info("DVF %s: downloading %s", year, url)
        http_meta = _download_to_file(url, dest, client)
        logger.info("DVF %s: download complete", year)

    size = dest.stat().st_size
    checksum = _sha256(dest)
    record = {
        "source_year": year,
        "source_url": url,
        "local_path": str(dest.relative_to(raw_root.parents[2]))
        if raw_root.parents[2] in dest.parents
        else str(dest),
        "acquired_at_utc": _utc_now_iso() if not reused
        else (manifest_entry.get("acquired_at_utc") if manifest_entry else _utc_now_iso()),
        "content_length": http_meta.get("content_length")
        or (manifest_entry.get("content_length") if manifest_entry else None),
        "last_modified": http_meta.get("last_modified")
        or (manifest_entry.get("last_modified") if manifest_entry else None),
        "compressed_size_bytes": size,
        "sha256": checksum,
        "reused_existing": reused,
    }
    manifest.setdefault("files", {})[str(year)] = record
    logger.info("DVF %s: size=%d bytes sha256=%s reused=%s",
                year, size, checksum[:16], reused)
    return record


def acquire_all(
    raw_root: Path,
    years: tuple[int, ...] = DVF_YEARS,
) -> dict[str, Any]:
    """Acquire all authorized years, maintaining the manifest.

    ``raw_root`` is ``data/raw/dvf``. Returns the updated manifest.
    """
    manifest_path = raw_root / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["updated_at_utc"] = _utc_now_iso()

    timeout = httpx.Timeout(DOWNLOAD_TIMEOUT, connect=CONNECT_TIMEOUT)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for year in years:
            acquire_year(year, raw_root, manifest, client)

    save_manifest(manifest_path, manifest)
    logger.info("DVF acquisition complete; manifest -> %s", manifest_path)
    return manifest
