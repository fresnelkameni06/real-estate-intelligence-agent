"""Unit tests for the RAG downloader using mocked HTTP (no network)."""

from __future__ import annotations

import httpx

from real_estate_agent.ingestion.documents.downloader import (
    download_source,
    host_allowed,
)
from real_estate_agent.ingestion.documents.models import SourceEntry

PDF_BYTES = b"%PDF-1.7\n" + b"x" * 200
HTML_BYTES = b"<!doctype html><html><body>ok</body></html>"


def _source(**over) -> SourceEntry:
    data = {
        "source_id": "comprendre_mon_dpe",
        "title": "Comprendre mon DPE",
        "publisher": "Ministère",
        "source_page_url": "https://www.ecologie.gouv.fr/x",
        "download_url": "https://www.ecologie.gouv.fr/x.pdf",
        "document_format": "pdf",
        "expected_content_types": ["application/pdf"],
        "authority_level": "official_guidance",
    }
    data.update(over)
    return SourceEntry.model_validate(data)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=True)


def _resp(content: bytes, status: int = 200,
          content_type: str = "application/pdf", **headers) -> httpx.Response:
    h = {"content-type": content_type, **headers}
    return httpx.Response(status, content=content, headers=h)


# --------------------------------------------------------------------------- #
# Host allowlist / HTTPS
# --------------------------------------------------------------------------- #

def test_host_allowed():
    assert host_allowed("https://www.ecologie.gouv.fr/a.pdf")
    assert not host_allowed("https://evil.example.com/a.pdf")


def test_unauthorized_host_rejected(tmp_path):
    entry = download_source(
        _source(download_url="https://evil.example.com/x.pdf"),
        tmp_path, client=_client(lambda r: _resp(PDF_BYTES)),
    )
    assert entry.status == "failed"
    assert "allowlist" in entry.error


# --------------------------------------------------------------------------- #
# Valid downloads
# --------------------------------------------------------------------------- #

def test_valid_pdf_download(tmp_path):
    entry = download_source(_source(), tmp_path,
                            client=_client(lambda r: _resp(PDF_BYTES)))
    assert entry.status == "downloaded"
    assert entry.sha256 is not None
    assert entry.byte_size == len(PDF_BYTES)
    assert (tmp_path / "comprendre_mon_dpe.pdf").exists()


def test_valid_html_download(tmp_path):
    s = _source(source_id="page", document_format="html",
                download_url="https://www.ecologie.gouv.fr/page",
                expected_content_types=["text/html"])
    entry = download_source(
        s, tmp_path,
        client=_client(lambda r: _resp(HTML_BYTES, content_type="text/html")),
    )
    assert entry.status == "downloaded"
    assert (tmp_path / "page.html").exists()


# --------------------------------------------------------------------------- #
# Validation failures
# --------------------------------------------------------------------------- #

def test_invalid_pdf_signature(tmp_path):
    entry = download_source(_source(), tmp_path,
                            client=_client(lambda r: _resp(b"NOTPDF" * 20)))
    assert entry.status == "failed"
    assert "%PDF-" in entry.error


def test_unexpected_content_type(tmp_path):
    entry = download_source(
        _source(), tmp_path,
        client=_client(lambda r: _resp(PDF_BYTES, content_type="text/plain")),
    )
    assert entry.status == "failed"
    assert "content type" in entry.error.lower()


def test_empty_content(tmp_path):
    entry = download_source(_source(), tmp_path,
                            client=_client(lambda r: _resp(b"")))
    assert entry.status == "failed"


def test_max_size_enforced(tmp_path):
    big = b"%PDF-1.7\n" + b"y" * (2 * 1024 * 1024)
    entry = download_source(_source(), tmp_path, max_size_mb=1,
                            client=_client(lambda r: _resp(big)))
    assert entry.status == "failed"
    assert "max size" in entry.error.lower()


# --------------------------------------------------------------------------- #
# Redirect host revalidation
# --------------------------------------------------------------------------- #

def test_redirect_to_disallowed_host(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ecologie.gouv.fr":
            return httpx.Response(302, headers={"location": "https://evil.com/x.pdf"})
        return _resp(PDF_BYTES)
    entry = download_source(_source(), tmp_path, client=_client(handler))
    assert entry.status == "failed"
    assert "disallowed host" in entry.error.lower()


# --------------------------------------------------------------------------- #
# Idempotence / preservation / cleanup
# --------------------------------------------------------------------------- #

def test_unchanged_when_same_checksum(tmp_path):
    c = _client(lambda r: _resp(PDF_BYTES))
    first = download_source(_source(), tmp_path, client=c)
    assert first.status == "downloaded"
    second = download_source(_source(), tmp_path, client=_client(lambda r: _resp(PDF_BYTES)))
    assert second.status == "unchanged"


def test_updated_when_content_changes(tmp_path):
    download_source(_source(), tmp_path, client=_client(lambda r: _resp(PDF_BYTES)))
    changed = b"%PDF-1.7\n" + b"z" * 300
    entry = download_source(_source(), tmp_path,
                            client=_client(lambda r: _resp(changed)))
    assert entry.status == "updated"


def test_existing_file_preserved_on_failure(tmp_path):
    # First, a good download.
    download_source(_source(), tmp_path, client=_client(lambda r: _resp(PDF_BYTES)))
    dest = tmp_path / "comprendre_mon_dpe.pdf"
    original = dest.read_bytes()
    # Then a failing retrieval (bad signature) must not overwrite the good file.
    entry = download_source(_source(), tmp_path,
                            client=_client(lambda r: _resp(b"BROKEN" * 10)))
    assert entry.status == "failed"
    assert dest.read_bytes() == original  # preserved


def test_part_file_cleaned_on_failure(tmp_path):
    download_source(_source(), tmp_path,
                    client=_client(lambda r: _resp(b"BROKEN" * 10)))
    assert not (tmp_path / "comprendre_mon_dpe.pdf.part").exists()


def test_sha256_is_deterministic(tmp_path):
    e1 = download_source(_source(), tmp_path,
                         client=_client(lambda r: _resp(PDF_BYTES)))
    import hashlib
    assert e1.sha256 == hashlib.sha256(PDF_BYTES).hexdigest()


def test_http_error_status(tmp_path):
    entry = download_source(_source(), tmp_path,
                            client=_client(lambda r: _resp(b"", status=404)))
    assert entry.status == "failed"
