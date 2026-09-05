"""Deterministic extraction of ordered elements from HTML and PDF bytes.

HTML: BeautifulSoup with the stdlib parser; strips scripts/styles/nav/footer/
forms and common interface blocks, selects the main content region, and keeps
headings, paragraphs, list items and useful table rows in original order.

PDF: pypdf page by page, preserving page numbers, with per-page warnings.
"""

from __future__ import annotations

import io

from bs4 import BeautifulSoup, Tag

from real_estate_agent.processing.documents.cleaning import clean_inline, clean_text
from real_estate_agent.processing.documents.models import DocumentElement

# Tags removed entirely (structure/interface, never documentary content).
_STRIP_TAGS = (
    "script", "style", "noscript", "template", "nav", "footer", "header",
    "form", "aside", "svg", "button", "iframe",
)

# CSS-ish class/id substrings that indicate interface-only blocks.
_NOISE_HINTS = (
    "cookie", "newsletter", "breadcrumb", "share", "social", "menu",
    "nav", "footer", "header", "sidebar", "pagination", "search",
    "skip-link", "back-to-top", "consent", "banner",
)

# Exact interface labels to drop (case-insensitive).
_INTERFACE_LABELS = frozenset(
    s.lower() for s in (
        "République Française", "Republique Francaise",
        "Se connecter", "S'enregistrer",
        "Ressources communautaires", "Informations", "Télécharger", "Telecharger",
        "Menu", "Rechercher", "Connexion", "Inscription", "Accueil",
        "Partager", "Imprimer", "Fermer", "Retour", "Suivant", "Précédent",
        "Precedent", "Paramètres d'affichage", "Parametres d'affichage",
    )
)

# Short interface fragments like "Fichiers 9", "Réutilisations et API 230".
_INTERFACE_PREFIXES = (
    "fichiers", "réutilisations", "reutilisations", "discussions",
    "ressources communautaires",
)

_BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr"]
_MAX_TABLE_ROW_CHARS = 2000


def _attr_text(tag: Tag, name: str) -> str:
    """Safely read an attribute as text, tolerating missing/None attrs."""
    attrs = getattr(tag, "attrs", None)
    if not attrs:
        return ""
    value = attrs.get(name)
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _looks_like_interface(text: str) -> bool:
    low = text.strip().lower()
    if low in _INTERFACE_LABELS:
        return True
    if len(low) <= 40:
        for prefix in _INTERFACE_PREFIXES:
            if low.startswith(prefix):
                return True
    return False


def _tag_is_noise(tag: Tag) -> bool:
    """Return True if a tag's class/id/role marks it as interface-only."""
    ident = " ".join(
        filter(None, [
            _attr_text(tag, "class"),
            _attr_text(tag, "id"),
            _attr_text(tag, "role"),
        ])
    ).strip().lower()
    if not ident:
        return False
    return any(hint in ident for hint in _NOISE_HINTS)


def _select_main(soup: BeautifulSoup) -> Tag:
    """Pick the main content region: largest <article>, else <main>/role=main."""
    articles = soup.find_all("article")
    if articles:
        return max(articles, key=lambda a: len(a.get_text()))
    main = soup.find("main")
    if not isinstance(main, Tag):
        main = soup.find(attrs={"role": "main"})
    if isinstance(main, Tag):
        return main
    return soup.body or soup


def extract_html(raw: bytes) -> tuple[list[DocumentElement], list[str]]:
    """Extract ordered elements from HTML bytes."""
    warnings: list[str] = []
    soup = BeautifulSoup(raw, "html.parser")

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    main = _select_main(soup)

    # Remove interface-only subtrees inside the main region.
    for tag in list(main.find_all(True)):
        if isinstance(tag, Tag) and _tag_is_noise(tag):
            tag.decompose()

    elements: list[DocumentElement] = []
    order = 0
    last_text: str | None = None

    for node in main.find_all(_BLOCK_TAGS):
        name = node.name
        if name and len(name) == 2 and name[0] == "h" and name[1].isdigit():
            kind = "heading"
            level: int | None = int(name[1])
        elif name == "p":
            kind, level = "paragraph", None
        elif name == "li":
            kind, level = "list_item", None
        else:  # tr
            kind, level = "table_row", None

        if kind == "table_row":
            cells = [clean_inline(c.get_text()) for c in node.find_all(["td", "th"])]
            text = " | ".join(c for c in cells if c)
            if len(text) > _MAX_TABLE_ROW_CHARS:
                text = text[:_MAX_TABLE_ROW_CHARS]
        else:
            text = clean_inline(node.get_text())

        if not text:
            continue
        if _looks_like_interface(text):
            continue
        if text == last_text:  # consecutive duplicate
            continue

        elements.append(DocumentElement(
            order=order, kind=kind, text=text,
            page_number=None, heading_level=level,
        ))
        order += 1
        last_text = text

    if not elements:
        warnings.append("No documentary elements extracted from HTML.")
    return elements, warnings


def extract_pdf(raw: bytes) -> tuple[list[DocumentElement], list[str]]:
    """Extract ordered page elements from PDF bytes using pypdf."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    warnings: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(raw))
    except (PdfReadError, OSError, ValueError) as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:  # 0 => failed
                raise ValueError("Encrypted PDF cannot be opened.")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Encrypted PDF cannot be opened: {exc}") from exc

    elements: list[DocumentElement] = []
    order = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = clean_text(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - continue on a bad page
            warnings.append(f"Page {i}: extraction error ({type(exc).__name__}).")
            continue
        if not text:
            warnings.append(f"Page {i}: empty or unreadable.")
            continue
        elements.append(DocumentElement(
            order=order, kind="page", text=text, page_number=i, heading_level=None,
        ))
        order += 1

    if not elements:
        raise ValueError("No usable text extracted from any PDF page.")
    return elements, warnings
