"""Page-aware text chunking (Phase 2).

Rules:
- A chunk never spans pages; page_start == page_end always.
- The most recent heading travels with each chunk as context.
- Table blocks become dedicated chunks (row-split with repeated headers only
  when a single table exceeds the budget).
- Other blocks are packed per page and char-split with overlap only when an
  individual packing unit exceeds the budget.
- block_types for a chunk come from exact block-offset mapping, not guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from models import Block, ParsedDocument

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class TextChunk:
    text: str
    page: int
    block_types: tuple


def split_chars(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """Character windows over text, preferring paragraph/sentence boundaries.
    Returns (start, end) ranges into text."""
    if size <= 0:
        raise ValueError("size must be greater than zero")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be nonnegative and smaller than size")
    if len(text) <= size:
        return [(0, len(text))] if text else []
    ranges, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", start, end)
            if cut > start + size // 2:
                end = cut
            else:
                cuts = [text.rfind(m, start + size // 2, end) for m in (". ", "? ", "! ", "; ")]
                cut = max(cuts)
                if cut >= start + size // 2:
                    end = cut + 1
        ranges.append((start, end))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return ranges


def _serialize_table(block: Block, size: int) -> list[str]:
    """One table block -> one chunk, or header-repeated row groups if oversize."""
    lines = block.text.split("\n")
    if sum(len(line) + 1 for line in lines) <= size:
        return ["\n".join(lines)]
    header, rows = lines[0], lines[1:]
    out, current = [], header
    for row in rows:
        if len(current) + len(row) + 2 > size:
            out.append(current)
            current = header
        current += "\n" + row
    out.append(current)
    return out


def build_text_chunks(doc: ParsedDocument, size: int, overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    heading_ctx = ""
    for page in doc.pages:
        segments: list[tuple[str, str]] = []  # (block_type, text)
        for block in page.blocks:
            if block.type == "heading" and block.text.strip():
                heading_ctx = _WS.sub(" ", block.text).strip()
                segments.append(("heading", heading_ctx))
            elif block.type == "table":
                for piece in _serialize_table(block, size):
                    prefix = f"{heading_ctx}\n" if heading_ctx else ""
                    chunks.append(TextChunk(f"{prefix}Table (p{page.number}):\n{piece}", page.number, ("heading", "table") if heading_ctx else ("table",)))
            elif block.type == "figure":
                continue  # Phase 3 owns figure records; no text to index here
            elif block.text.strip():
                # Collapse line-break hyphenation artifacts in prose; table
                # cells keep their newlines (row structure matters there).
                segments.append((block.type, _WS.sub(" ", block.text).strip()))
        if not segments:
            continue
        joined, offsets, pos = "", [], 0
        for btype, text in segments:
            offsets.append((btype, pos, pos + len(text)))
            joined += text + "\n\n"
            pos += len(text) + 2
        joined = joined.rstrip("\n")
        for start, end in split_chars(joined, size, overlap):
            types = {t for t, s, e in offsets if s < end and e > start}
            prefix = ""
            if heading_ctx and not joined[start:end].lstrip().startswith(heading_ctx):
                prefix = heading_ctx + "\n\n"
                types.add("heading")
            chunks.append(TextChunk(prefix + joined[start:end].strip(), page.number, tuple(sorted(types))))
    return chunks
