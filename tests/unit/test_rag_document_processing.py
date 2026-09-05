"""Unit tests for RAG document processing (deterministic, offline)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from real_estate_agent.ingestion.documents.models import SourceEntry
from real_estate_agent.processing.documents.cleaning import clean_inline, clean_text
from real_estate_agent.processing.documents.extractor import extract_html, extract_pdf
from real_estate_agent.processing.documents.pipeline import (
    load_manifest,
    process_source,
)

# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #

def test_whitespace_normalization():
    assert clean_inline("a\t\t b   c") == "a b c"


def test_nbsp_and_soft_hyphen():
    assert clean_inline("a\u00a0b\u00adc") == "a bc"


def test_html_entities_unescaped():
    assert clean_inline("&eacute;nergie &amp; climat") == "énergie & climat"


def test_line_endings_and_blank_lines():
    out = clean_text("a\r\n\r\n\r\n\r\nb")
    assert out == "a\n\nb"


def test_paragraph_boundaries_preserved():
    out = clean_text("Paragraphe un.\n\nParagraphe deux.")
    assert out == "Paragraphe un.\n\nParagraphe deux."


# --------------------------------------------------------------------------- #
# HTML extraction
# --------------------------------------------------------------------------- #

_NOISY_HTML = b"""<html><head><script>x=1</script><style>.a{}</style></head>
<body>
<nav class="menu">Accueil Rechercher</nav>
<header>R\xc3\xa9publique Fran\xc3\xa7aise Se connecter S'enregistrer</header>
<article>
<h1>Demandes de valeurs fonci\xc3\xa8res</h1>
<p>Les DVF recensent l'ensemble des &eacute;changes de biens immobiliers
survenus au cours des cinq derni\xc3\xa8res ann\xc3\xa9es sur le territoire, \xc3\xa0
l'exception de l'Alsace, de la Moselle et de Mayotte. Elles proviennent des
actes notari\xc3\xa9s et des informations cadastrales.</p>
<p>Fichiers 9</p>
<p>R\xc3\xa9utilisations et API 230</p>
<p>Ce jeu de donn\xc3\xa9es permet de conna\xc3\xaetre les transactions immobili\xc3\xa8res
intervenues, avec le prix, l'adresse, la surface et la nature du bien vendu.</p>
<ul><li>Prix de vente du bien immobilier</li><li>Surface r\xc3\xa9elle b\xc3\xa2tie</li></ul>
<table><tr><td>Ann\xc3\xa9e</td><td>2024</td></tr></table>
<p>T\xc3\xa9l\xc3\xa9charger</p>
<footer class="footer">Discussions 124</footer>
</article>
<div class="cookie-banner">Accepter les cookies</div>
</body></html>"""


def test_html_removes_script_style_nav_footer():
    elements, _ = extract_html(_NOISY_HTML)
    texts = [e.text for e in elements]
    assert not any("x=1" in t for t in texts)
    assert not any("Accueil" in t for t in texts)
    assert not any("Discussions" in t for t in texts)


def test_html_removes_datagouv_interface_labels():
    elements, _ = extract_html(_NOISY_HTML)
    texts = [e.text for e in elements]
    for noise in ("Se connecter", "S'enregistrer", "Fichiers 9",
                  "Réutilisations et API 230", "Télécharger",
                  "République Française"):
        assert noise not in texts


def test_html_preserves_documentary_content():
    elements, _ = extract_html(_NOISY_HTML)
    kinds = {e.kind for e in elements}
    texts = [e.text for e in elements]
    assert "heading" in kinds
    assert "paragraph" in kinds
    assert "list_item" in kinds
    assert "table_row" in kinds
    assert any("DVF recensent" in t for t in texts)
    assert any("Surface réelle bâtie" in t for t in texts)


def test_html_heading_level_and_order():
    elements, _ = extract_html(_NOISY_HTML)
    orders = [e.order for e in elements]
    assert orders == sorted(orders)  # strictly ordered
    heading = next(e for e in elements if e.kind == "heading")
    assert heading.heading_level == 1


def test_html_removes_consecutive_duplicates():
    html = b"<article><p>Meme texte</p><p>Meme texte</p><p>Autre</p></article>"
    elements, _ = extract_html(html)
    texts = [e.text for e in elements]
    assert texts == ["Meme texte", "Autre"]


# --------------------------------------------------------------------------- #
# PDF extraction (mocked PdfReader)
# --------------------------------------------------------------------------- #

def _mock_reader(pages_text, encrypted=False):  # noqa: ANN001
    reader = MagicMock()
    reader.is_encrypted = encrypted
    pages = []
    for txt in pages_text:
        p = MagicMock()
        p.extract_text.return_value = txt
        pages.append(p)
    reader.pages = pages
    return reader


def test_pdf_page_numbers_preserved():
    reader = _mock_reader(["Contenu page une.", "Contenu page deux."])
    with patch("pypdf.PdfReader", return_value=reader):
        elements, warnings = extract_pdf(b"%PDF-x")
    assert [e.page_number for e in elements] == [1, 2]
    assert all(e.kind == "page" for e in elements)


def test_pdf_empty_page_warning_and_continue():
    reader = _mock_reader(["Bon contenu de page.", ""])
    with patch("pypdf.PdfReader", return_value=reader):
        elements, warnings = extract_pdf(b"%PDF-x")
    assert len(elements) == 1
    assert any("Page 2" in w for w in warnings)


def test_pdf_no_text_raises():
    reader = _mock_reader(["", "  "])
    with patch("pypdf.PdfReader", return_value=reader):
        with pytest.raises(ValueError, match="No usable text"):
            extract_pdf(b"%PDF-x")


def test_pdf_invalid_bytes_raises():
    with pytest.raises(ValueError, match="Cannot open PDF"):
        extract_pdf(b"not a pdf at all")


# --------------------------------------------------------------------------- #
# Pipeline: checksum, manifest, output, idempotence
# --------------------------------------------------------------------------- #

def _source(**over) -> SourceEntry:
    data = {
        "source_id": "dvf_dataset_page",
        "title": "DVF",
        "publisher": "data.gouv.fr",
        "source_page_url": "https://www.data.gouv.fr/datasets/x",
        "download_url": "https://www.data.gouv.fr/datasets/x",
        "document_format": "html",
        "expected_content_types": ["text/html"],
        "authority_level": "dataset_methodology",
    }
    data.update(over)
    return SourceEntry.model_validate(data)


def _setup(tmp_path, content: bytes, ext: str = "html"):
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    raw_dir.mkdir()
    raw_path = raw_dir / f"dvf_dataset_page.{ext}"
    raw_path.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    manifest = {"dvf_dataset_page": {"source_id": "dvf_dataset_page",
                                     "status": "downloaded", "sha256": sha}}
    return raw_dir, proc_dir, manifest, sha


def test_pipeline_creates_output(tmp_path):
    raw_dir, proc_dir, manifest, sha = _setup(tmp_path, _NOISY_HTML)
    res = process_source(_source(), raw_dir, proc_dir, manifest)
    assert res["status"] == "processed"
    out = proc_dir / "dvf_dataset_page.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["raw_sha256"] == sha
    assert data["source_id"] == "dvf_dataset_page"
    assert data["total_characters"] > 0
    assert data["elements"]


def test_pipeline_checksum_mismatch_rejected(tmp_path):
    raw_dir, proc_dir, manifest, _ = _setup(tmp_path, _NOISY_HTML)
    manifest["dvf_dataset_page"]["sha256"] = "0" * 64  # wrong
    res = process_source(_source(), raw_dir, proc_dir, manifest)
    assert res["status"] == "failed"
    assert "mismatch" in res["error"].lower()


def test_pipeline_missing_manifest_entry_rejected(tmp_path):
    raw_dir, proc_dir, _, _ = _setup(tmp_path, _NOISY_HTML)
    res = process_source(_source(), raw_dir, proc_dir, {})
    assert res["status"] == "failed"
    assert "manifest" in res["error"].lower()


def test_pipeline_failed_manifest_entry_rejected(tmp_path):
    raw_dir, proc_dir, manifest, _ = _setup(tmp_path, _NOISY_HTML)
    manifest["dvf_dataset_page"]["status"] = "failed"
    res = process_source(_source(), raw_dir, proc_dir, manifest)
    assert res["status"] == "failed"


def test_pipeline_too_short_rejected(tmp_path):
    raw_dir, proc_dir, manifest, _ = _setup(
        tmp_path, b"<article><p>court</p></article>"
    )
    res = process_source(_source(), raw_dir, proc_dir, manifest,
                         min_characters=200)
    assert res["status"] == "failed"
    assert "too short" in res["error"].lower()


def test_pipeline_idempotent_unchanged(tmp_path):
    raw_dir, proc_dir, manifest, _ = _setup(tmp_path, _NOISY_HTML)
    first = process_source(_source(), raw_dir, proc_dir, manifest)
    assert first["status"] == "processed"
    second = process_source(_source(), raw_dir, proc_dir, manifest)
    assert second["status"] == "unchanged"


def test_pipeline_force_reprocesses(tmp_path):
    raw_dir, proc_dir, manifest, _ = _setup(tmp_path, _NOISY_HTML)
    process_source(_source(), raw_dir, proc_dir, manifest)
    res = process_source(_source(), raw_dir, proc_dir, manifest, force=True)
    assert res["status"] == "processed"


def test_pipeline_no_part_file_left(tmp_path):
    raw_dir, proc_dir, manifest, _ = _setup(tmp_path, _NOISY_HTML)
    process_source(_source(), raw_dir, proc_dir, manifest)
    parts = list(proc_dir.glob("*.part"))
    assert parts == []


def test_load_manifest_missing(tmp_path):
    from real_estate_agent.processing.documents.pipeline import ProcessingError
    with pytest.raises(ProcessingError, match="not found"):
        load_manifest(Path(tmp_path / "nope.json"))
