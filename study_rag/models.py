"""Stable records for structured document extraction (Phase 1).

The ingestion pipeline must depend on these records — not on any specific
parser library. Backends live in document_parser.py and convert their native
output into this shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

BlockType = Literal["heading", "paragraph", "table", "caption", "figure", "list"]


@dataclass(frozen=True)
class BBox:
    """Bounding box in PDF points, origin top-left. None when unknown (fallback)."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Block:
    """One ordered content unit on a page."""

    block_id: str  # stable: f"{document_id}:p{page}:{order:03d}"
    page: int  # 1-based page number
    order: int  # 0-based position within the page
    type: BlockType
    text: str  # "" for figures without extracted labels
    bbox: Optional[BBox] = None
    asset_path: Optional[str] = None  # local figure image, relative to ARTIFACT_DIR
    extra: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ParsedPage:
    number: int  # 1-based
    width: float
    height: float
    blocks: tuple
    has_text_layer: bool  # False for scanned/image-only pages


@dataclass(frozen=True)
class ParsedDocument:
    source: str  # path relative to data/raw/, posix style
    document_id: str  # stable sha256 of source; keys artifact dirs + chunk IDs
    parser_name: str  # e.g. "pymupdf", "pypdf", "docling"
    parser_version: str
    pages: tuple
    warnings: tuple = ()  # non-fatal issues, each names file and page

    @property
    def blocks(self) -> list:
        return [b for p in self.pages for b in p.blocks]

    @property
    def text_blocks(self) -> list:
        return [b for b in self.blocks if b.text.strip()]
