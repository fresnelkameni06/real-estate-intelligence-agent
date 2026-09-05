"""Structure-aware deterministic splitter for processed HTML and PDF documents."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from real_estate_agent.ingestion.documents.models import SourceEntry
from real_estate_agent.processing.documents.models import ProcessedDocument
from real_estate_agent.rag.chunking.models import (
    ChunkingConfig,
    DocumentChunk,
    QualityFlag,
)

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ0-9«])")
_PARAGRAPH_BOUNDARY_RE = re.compile(r"\n\s*\n")


class ChunkingError(RuntimeError):
    """Raised when a processed document cannot be chunked safely."""


@dataclass(frozen=True)
class _ContextBlock:
    text: str
    heading_path: tuple[str, ...]
    page_number: int | None


@dataclass(frozen=True)
class _DraftChunk:
    text: str
    heading_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    quality_flags: tuple[QualityFlag, ...] = ()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _heading_prefix(path: tuple[str, ...], maximum: int) -> str:
    """Keep the most useful complete headings within a conservative budget."""
    if not path:
        return ""
    selected: list[str] = []
    for heading in reversed(path):
        candidate = " > ".join(reversed([heading, *selected]))
        if len(candidate) > maximum:
            break
        selected.insert(0, heading)
    return " > ".join(selected)


def _split_words(text: str, limit: int) -> tuple[list[str], bool]:
    """Split on word boundaries; only a pathological token may exceed the limit."""
    words = text.split()
    pieces: list[str] = []
    current: list[str] = []
    pathological = False
    for word in words:
        if len(word) > limit:
            if current:
                pieces.append(" ".join(current))
                current = []
            pieces.append(word)
            pathological = True
            continue
        candidate = " ".join([*current, word])
        if current and len(candidate) > limit:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces, pathological


def _split_oversized(text: str, limit: int) -> tuple[list[str], bool]:
    """Prefer paragraph, line, sentence and finally word boundaries."""
    if len(text) <= limit:
        return [text.strip()], False

    pieces = [piece.strip() for piece in _PARAGRAPH_BOUNDARY_RE.split(text) if piece.strip()]
    if len(pieces) == 1:
        pieces = [piece.strip() for piece in text.splitlines() if piece.strip()]

    expanded: list[str] = []
    pathological = False
    for piece in pieces:
        if len(piece) <= limit:
            expanded.append(piece)
            continue
        sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(piece) if part.strip()]
        if len(sentences) == 1:
            word_pieces, has_pathological = _split_words(piece, limit)
            expanded.extend(word_pieces)
            pathological = pathological or has_pathological
            continue
        for sentence in sentences:
            if len(sentence) <= limit:
                expanded.append(sentence)
            else:
                word_pieces, has_pathological = _split_words(sentence, limit)
                expanded.extend(word_pieces)
                pathological = pathological or has_pathological
    return expanded, pathological


def _tail_on_word_boundary(text: str, limit: int) -> str:
    if limit <= 0 or not text:
        return ""
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    first_space = tail.find(" ")
    if first_space == -1:
        return ""
    return tail[first_space + 1 :].strip()


def _render(prefix: str, body: str) -> str:
    return f"{prefix}\n\n{body}" if prefix else body


def _split_context(
    blocks: list[_ContextBlock],
    config: ChunkingConfig,
) -> list[_DraftChunk]:
    """Chunk blocks that share one heading path and page context."""
    heading_path = blocks[0].heading_path
    page_numbers = [block.page_number for block in blocks if block.page_number is not None]
    page_start = min(page_numbers) if page_numbers else None
    page_end = max(page_numbers) if page_numbers else None
    prefix = _heading_prefix(heading_path, maximum=min(300, config.maximum_characters // 3))
    body_limit = config.maximum_characters - len(prefix) - (2 if prefix else 0)
    if body_limit < 50:
        raise ChunkingError("Heading context leaves insufficient room for chunk content.")

    units: list[str] = []
    pathological = False
    for block in blocks:
        split, has_pathological = _split_oversized(block.text, body_limit)
        units.extend(split)
        pathological = pathological or has_pathological

    drafts: list[_DraftChunk] = []
    current = ""
    current_has_pathological = False
    for index, unit in enumerate(units):
        separator = "\n\n" if current else ""
        candidate = f"{current}{separator}{unit}"
        rendered_candidate = _render(prefix, candidate)
        should_flush = bool(current) and len(rendered_candidate) > config.maximum_characters
        if should_flush:
            flags: tuple[QualityFlag, ...] = (
                ("pathological_token",) if current_has_pathological else ()
            )
            drafts.append(
                _DraftChunk(
                    text=_render(prefix, current),
                    heading_path=heading_path,
                    page_start=page_start,
                    page_end=page_end,
                    quality_flags=flags,
                )
            )
            overlap = _tail_on_word_boundary(current, config.overlap_characters)
            candidate = f"{overlap}\n\n{unit}" if overlap else unit
            if len(_render(prefix, candidate)) > config.maximum_characters:
                candidate = unit
            current = candidate
            current_has_pathological = len(unit) > body_limit
        else:
            current = candidate
            current_has_pathological = current_has_pathological or len(unit) > body_limit

        has_more = index < len(units) - 1
        if has_more and len(_render(prefix, current)) >= config.target_characters:
            flags = ("pathological_token",) if current_has_pathological else ()
            drafts.append(
                _DraftChunk(
                    text=_render(prefix, current),
                    heading_path=heading_path,
                    page_start=page_start,
                    page_end=page_end,
                    quality_flags=flags,
                )
            )
            current = _tail_on_word_boundary(current, config.overlap_characters)
            current_has_pathological = False

    if current:
        rendered = _render(prefix, current)
        if drafts and len(rendered) < config.minimum_chunk_characters:
            previous = drafts[-1]
            merged = f"{previous.text}\n\n{current}"
            if len(merged) <= config.maximum_characters:
                drafts[-1] = _DraftChunk(
                    text=merged,
                    heading_path=previous.heading_path,
                    page_start=previous.page_start,
                    page_end=previous.page_end,
                    quality_flags=previous.quality_flags,
                )
                return drafts
        flags = ("pathological_token",) if current_has_pathological or pathological else ()
        drafts.append(
            _DraftChunk(
                text=rendered,
                heading_path=heading_path,
                page_start=page_start,
                page_end=page_end,
                quality_flags=flags,
            )
        )
    return drafts


def _context_blocks(document: ProcessedDocument) -> list[_ContextBlock]:
    heading_stack: list[str] = []
    blocks: list[_ContextBlock] = []
    expected_order = 0
    for element in document.elements:
        if element.order != expected_order:
            raise ChunkingError("Processed document elements must have contiguous order values.")
        expected_order += 1
        text = element.text.strip()
        if not text:
            continue
        if element.kind == "heading":
            level = element.heading_level or 1
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(text)
            continue
        blocks.append(
            _ContextBlock(
                text=text,
                heading_path=tuple(heading_stack),
                page_number=element.page_number,
            )
        )
    if not blocks:
        raise ChunkingError("Processed document contains no chunkable content.")
    return blocks


def _group_by_context(blocks: list[_ContextBlock]) -> list[list[_ContextBlock]]:
    groups: list[list[_ContextBlock]] = []
    for block in blocks:
        key = (block.heading_path, block.page_number)
        if groups and (groups[-1][0].heading_path, groups[-1][0].page_number) == key:
            groups[-1].append(block)
        else:
            groups.append([block])
    return groups


def _merge_leading_preamble(
    drafts: list[_DraftChunk],
    config: ChunkingConfig,
) -> list[_DraftChunk]:
    """Keep a tiny HTML metadata preamble by attaching it to the first section."""
    if len(drafts) < 2:
        return drafts
    preamble, first_section = drafts[0], drafts[1]
    is_tiny_html_preamble = (
        not preamble.heading_path
        and preamble.page_start is None
        and first_section.page_start is None
        and len(preamble.text) < config.minimum_chunk_characters
        and bool(first_section.heading_path)
    )
    combined = f"{first_section.text}\n\n{preamble.text}"
    if not is_tiny_html_preamble or len(combined) > config.maximum_characters:
        return drafts
    merged = _DraftChunk(
        text=combined,
        heading_path=first_section.heading_path,
        page_start=None,
        page_end=None,
        quality_flags=tuple(
            dict.fromkeys([*preamble.quality_flags, *first_section.quality_flags])
        ),
    )
    return [merged, *drafts[2:]]


def chunk_document(
    document: ProcessedDocument,
    source: SourceEntry,
    config: ChunkingConfig,
) -> list[DocumentChunk]:
    """Create stable, validated chunks without calling an LLM or tokenizer."""
    if document.source_id != source.source_id:
        raise ChunkingError("Processed document source_id does not match registry source.")
    if not document.raw_sha256 or len(document.raw_sha256) != 64:
        raise ChunkingError("Processed document has invalid raw SHA-256 provenance.")

    source_flags: list[QualityFlag] = []
    if document.total_characters < config.short_document_warning_threshold:
        source_flags.append("limited_source_content")

    drafts: list[_DraftChunk] = []
    for group in _group_by_context(_context_blocks(document)):
        drafts.extend(_split_context(group, config))
    drafts = _merge_leading_preamble(drafts, config)

    chunks: list[DocumentChunk] = []
    seen_text_hashes: set[str] = set()
    for draft in drafts:
        text = draft.text.strip()
        content_sha256 = _sha256_text(text)
        if content_sha256 in seen_text_hashes:
            continue
        seen_text_hashes.add(content_sha256)
        flags = list(dict.fromkeys([*source_flags, *draft.quality_flags]))
        chunk_id = _sha256_text(
            ":".join(
                [
                    source.source_id,
                    document.raw_sha256,
                    config.chunking_version,
                    str(len(chunks)),
                    content_sha256,
                ]
            )
        )
        chunks.append(
            DocumentChunk(
                chunking_version=config.chunking_version,
                chunk_id=chunk_id,
                source_id=source.source_id,
                chunk_index=len(chunks),
                text=text,
                character_count=len(text),
                word_count=len(text.split()),
                content_sha256=content_sha256,
                title=source.title,
                publisher=source.publisher,
                source_page_url=source.source_page_url,
                download_url=source.download_url,
                document_format=source.document_format,
                raw_sha256=document.raw_sha256,
                heading_path=list(draft.heading_path),
                page_start=draft.page_start,
                page_end=draft.page_end,
                topics=source.topics,
                language=source.language,
                jurisdiction=source.jurisdiction,
                authority_level=source.authority_level,
                is_normative=source.is_normative,
                effective_from=source.effective_from,
                effective_until=source.effective_until,
                quality_flags=flags,
            )
        )

    if not chunks:
        raise ChunkingError("Chunking produced no unique chunks.")
    ids = [chunk.chunk_id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ChunkingError("Chunking produced duplicate chunk IDs.")
    for chunk in chunks:
        if chunk.character_count > config.maximum_characters:
            if "pathological_token" not in chunk.quality_flags:
                raise ChunkingError("Chunk exceeds maximum_characters without a quality flag.")
    return chunks
