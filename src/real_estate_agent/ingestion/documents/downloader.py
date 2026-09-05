"""Secure downloader for approved RAG documents.

Security properties:
  * only HTTPS URLs from the registry (never arbitrary CLI URLs);
  * hostname checked against an explicit allowlist, revalidated after redirects;
  * streaming download with an explicit timeout and a configurable size cap;
  * PDF signature (%PDF-) and plausible-HTML checks; unexpected types rejected;
  * writes to a temporary .part file, atomically replaces the destination only
    after validation, and never overwrites a valid file when a retrieval fails;
  * records provenance: SHA-256, byte size, UTC time, requested/final URL, HTTP
    status, ETag and Last-Modified; classifies new/updated/unchanged/failed.

Filenames derive only from validated source_id values.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from real_estate_agent.ingestion.documents.models import ManifestEntry, SourceEntry

logger = logging.getLogger(__name__)

# Explicit allowlist of official hosts. Any other host is rejected, including
# after a redirect.
ALLOWED_HOSTS = frozenset({
    "www.ecologie.gouv.fr",
    "ecologie.gouv.fr",
    "www2.ecologie.gouv.fr",
    "www.data.gouv.fr",
    "data.gouv.fr",
    "static.data.gouv.fr",
    "files.data.gouv.fr",
    "data.ademe.fr",
})

USER_AGENT = "RealEstateIntelligenceAgent/0.1 (+official-document-acquisition)"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
DEFAULT_MAX_SIZE_MB = 25
_CHUNK = 64 * 1024


class DownloadError(RuntimeError):
    """Raised for a controlled download validation failure."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def host_allowed(url: str) -> bool:
    """Return True if the URL host is in the allowlist."""
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOWED_HOSTS


def _looks_like_html(head: bytes) -> bool:
    sample = head[:512].lstrip().lower()
    return sample.startswith((b"<!doctype html", b"<html")) or b"<html" in sample


def _validate_payload(fmt: str, path: Path) -> None:
    """Validate the downloaded file's content by format; raise on failure."""
    if path.stat().st_size == 0:
        raise DownloadError("Empty content.")
    with path.open("rb") as fh:
        head = fh.read(512)
    if fmt == "pdf":
        if not head.startswith(b"%PDF-"):
            raise DownloadError("File does not start with the %PDF- signature.")
    elif fmt == "html":
        if not _looks_like_html(head):
            raise DownloadError("Response does not look like HTML.")
    else:
        raise DownloadError(f"Unsupported format: {fmt}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_type_ok(content_type: str | None, expected: list[str]) -> bool:
    if content_type is None:
        return False
    ct = content_type.split(";")[0].strip().lower()
    return any(ct == e.lower() for e in expected)


def download_source(
    source: SourceEntry,
    dest_dir: Path,
    *,
    max_size_mb: int = DEFAULT_MAX_SIZE_MB,
    force: bool = False,
    client: httpx.Client | None = None,
) -> ManifestEntry:
    """Download one approved source with full validation and provenance.

    Returns a ManifestEntry. On failure, any existing valid file is preserved.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = "pdf" if source.document_format == "pdf" else "html"
    dest = dest_dir / f"{source.source_id}.{ext}"
    part = dest.with_suffix(dest.suffix + ".part")

    entry = ManifestEntry(
        source_id=source.source_id,
        title=source.title,
        requested_url=source.download_url,
        status="failed",
    )

    # Guard: only HTTPS + allowlisted host (pre-request check).
    if not source.download_url.startswith("https://"):
        entry.error = "Non-HTTPS URL rejected."
        return entry
    if not host_allowed(source.download_url):
        entry.error = f"Host not in allowlist: {urlparse(source.download_url).hostname}"
        return entry

    previous_sha = _sha256(dest) if dest.exists() else None
    max_bytes = max_size_mb * 1024 * 1024

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=DEFAULT_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    try:
        if part.exists():
            part.unlink()
        with client.stream("GET", source.download_url) as resp:
            entry.http_status = resp.status_code
            entry.final_url = str(resp.url)
            entry.content_type = resp.headers.get("content-type")
            entry.etag = resp.headers.get("etag")
            entry.last_modified = resp.headers.get("last-modified")

            # Revalidate the final host after redirects.
            if not host_allowed(str(resp.url)):
                raise DownloadError(
                    f"Redirected to disallowed host: {urlparse(str(resp.url)).hostname}"
                )
            resp.raise_for_status()

            if not _content_type_ok(entry.content_type, source.expected_content_types):
                raise DownloadError(f"Unexpected content type: {entry.content_type}")

            written = 0
            with part.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=_CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise DownloadError(
                            f"File exceeds max size ({max_size_mb} MB)."
                        )
                    fh.write(chunk)

        # Validate the payload before committing.
        _validate_payload(source.document_format, part)

        new_sha = _sha256(part)
        entry.sha256 = new_sha
        entry.byte_size = part.stat().st_size
        entry.retrieved_at_utc = _utc_now_iso()

        if previous_sha is not None and previous_sha == new_sha and not force:
            # Unchanged: keep the existing valid file, drop the .part.
            part.unlink(missing_ok=True)
            entry.local_path = str(dest)
            entry.status = "unchanged"
            logger.info("%s: unchanged (checksum match)", source.source_id)
            return entry

        # Atomic replace (same directory).
        part.replace(dest)
        entry.local_path = str(dest)
        entry.status = "updated" if previous_sha is not None else "downloaded"
        logger.info("%s: %s (%d bytes)", source.source_id, entry.status,
                    entry.byte_size)
        return entry

    except (httpx.HTTPError, DownloadError, OSError) as exc:
        # Never overwrite/remove the latest valid file on failure.
        part.unlink(missing_ok=True)
        entry.status = "failed"
        entry.error = f"{type(exc).__name__}: {exc}"[:500]
        if dest.exists():
            entry.local_path = str(dest)  # previous valid file preserved
        logger.warning("%s: download failed: %s", source.source_id, entry.error)
        return entry
    finally:
        if owns_client:
            client.close()
