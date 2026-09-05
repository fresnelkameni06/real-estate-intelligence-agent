"""Conservative, deterministic text cleaning.

Normalizes whitespace, Unicode, HTML entities and line endings WITHOUT
paraphrasing, summarizing or rewriting official/legal content. The meaning of
the source text is always preserved.
"""

from __future__ import annotations

import html
import re
import unicodedata

# Inline whitespace (spaces, tabs, non-breaking spaces) but NOT newlines.
_INLINE_WS = re.compile(r"[^\S\n]+")
# Three or more newlines collapse to a paragraph break (two newlines).
_EXCESS_BLANK = re.compile(r"\n{3,}")
_SOFT_HYPHEN = "\u00ad"


def clean_text(text: str) -> str:
    """Clean a block of text conservatively and deterministically."""
    if not text:
        return ""

    # Unescape HTML entities (e.g. &amp; -> &, &eacute; -> é).
    text = html.unescape(text)

    # Unicode normalization (NFC) for stable, comparable text.
    text = unicodedata.normalize("NFC", text)

    # Remove soft hyphens (invisible hyphenation hints).
    text = text.replace(_SOFT_HYPHEN, "")

    # Normalize non-breaking spaces / narrow NBSP to a regular space.
    text = text.replace("\u00a0", " ").replace("\u202f", " ")

    # Normalize line endings: CRLF/CR -> LF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse inline runs of whitespace (keep newlines).
    text = _INLINE_WS.sub(" ", text)

    # Trim trailing spaces on each line.
    text = "\n".join(line.strip() for line in text.split("\n"))

    # Collapse excessive blank lines.
    text = _EXCESS_BLANK.sub("\n\n", text)

    # Trim leading/trailing whitespace overall.
    return text.strip()


def clean_inline(text: str) -> str:
    """Clean a single inline element (no internal newlines expected)."""
    cleaned = clean_text(text)
    # For inline elements, flatten any residual newlines to single spaces.
    return _INLINE_WS.sub(" ", cleaned.replace("\n", " ")).strip()
