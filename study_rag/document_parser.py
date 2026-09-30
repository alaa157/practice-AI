#!/usr/bin/env python3
"""Parser adapter: every backend returns models.ParsedDocument.

Stable interface (Phase 1):

    parse_document(path, backend="auto", enable_ocr=False, export_figures=False)
        -> ParsedDocument

Backends:
  pymupdf - default. Instant, light, offline. Pages, reading-order blocks,
            heading detection, tables (find_tables), figure/image detection
            with bboxes, caption heuristic.
  docling - optional heavy backend (pip install docling). Layout + tableformer
            models, real table structure, and RapidOCR for scanned pages.
            First run downloads models (~1 GB); ~1 min for 3 small pages on
            2 CPUs. Selected automatically for PDFs when enable_ocr=True, or
            explicitly with backend="docling".
  pypdf   - explicit lightweight fallback. One text block per non-empty page;
            no bboxes, tables, or figures. Used only when requested or when
            selected as the automatic lightweight backend when PyMuPDF is absent.

Source PDFs are opened read-only. Figure assets (when export_figures=True) go
to ARTIFACT_DIR/<document_id>/figures/ — never next to the source.

OCR is an extraction feature for scanned pages, not diagram understanding.
Docling supplies the optional OCR backend; when it is unavailable, requesting
OCR with another backend records a warning and leaves scanned pages unindexed.
Parser failures do not silently switch to a different backend. See
eval/PARSER_EVALUATION.md for the backend decision log.

Inspect:  python document_parser.py data/raw/biology/cell_biology.pdf
"""

from __future__ import annotations

import hashlib
import re
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from config import ARTIFACT_DIR, RAW_DIR  # noqa: E402
from models import BBox, Block, ParsedDocument, ParsedPage  # noqa: E402

CAPTION_RE = re.compile(r"^(figure|table|fig\.)\s+\d+\s*:", re.IGNORECASE)


class ParseError(Exception):
    """Fatal parse failure. Message always names the file and page."""


def _document_id(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def _pkg(name: str) -> str:
    try:
        return _pkg_version(name)
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- PyMuPDF ---

def _page_body_size(text_blocks: list[dict]) -> float:
    """Median span size across the page — headings are measured against this,
    not against their own spans (a lone title span would compare to itself)."""
    sizes = sorted(s["size"] for b in text_blocks for line in b.get("lines", []) for s in line.get("spans", []) if s.get("text", "").strip())
    return sizes[len(sizes) // 2] if sizes else 0.0


def _classify_block(block: dict, body: float) -> str:
    spans = [s for line in block.get("lines", []) for s in line.get("spans", [])]
    text = "".join(s.get("text", "") for s in spans)
    if not text.strip() or not body:
        return "paragraph"
    big_chars = sum(len(s.get("text", "")) for s in spans if s["size"] > body * 1.25)
    if big_chars / len(text) > 0.6 and len(text) < 200:
        return "heading"
    return "paragraph"


def _parse_pymupdf(path: Path, source: str, doc_id: str, export_figures: bool) -> ParsedDocument:
    import pymupdf as fitz

    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ParseError(f"{source}: cannot open ({type(e).__name__}: {e})")
    pages: list[ParsedPage] = []
    warnings: list[str] = []
    try:
        for pno in range(len(doc)):
            page = doc[pno]
            blocks: list[Block] = []
            order = 0

            def add(btype, text, bbox=None, extra=None, asset=None):
                nonlocal order
                blocks.append(Block(f"{doc_id}:p{pno + 1}:{order:03d}", pno + 1, order, btype, text, bbox, asset, extra or {}))
                order += 1

            # Tables first (need bboxes to avoid double-counting overlapped text).
            table_rects = []
            try:
                tables = page.find_tables()
                for t in tables:
                    table_rects.append(fitz.Rect(t.bbox))
                    rows = []
                    for row in t.extract():
                        rows.append(" | ".join("" if c is None else str(c).strip() for c in row))
                    add("table", "\n".join(rows), BBox(*t.bbox), {"rows": len(rows)})
            except Exception as e:
                warnings.append(f"{source} p{pno + 1}: table detection failed ({e}); text kept as paragraphs")

            def in_table(r: fitz.Rect) -> bool:
                return any(r.intersects(tr) and r.get_area() < tr.get_area() * 1.5 for tr in table_rects)

            # Text blocks in reading order.
            try:
                data = page.get_text("dict")
            except Exception as e:
                raise ParseError(f"{source} p{pno + 1}: text extraction failed ({type(e).__name__}: {e})")
            text_blocks = [b for b in data.get("blocks", []) if b.get("type", 0) == 0]
            body = _page_body_size(text_blocks)
            for b in text_blocks:
                brect = fitz.Rect(b["bbox"])
                if in_table(brect):
                    continue
                spans = [s for line in b.get("lines", []) for s in line.get("spans", [])]
                text = "".join(s.get("text", "") for line in b.get("lines", []) for s in line.get("spans", [])).strip()
                if not text:
                    continue
                btype = _classify_block(b, body)
                if btype == "paragraph" and CAPTION_RE.match(text):
                    btype = "caption"
                add(btype, text, BBox(*b["bbox"]))

            # Figures: embedded images mapped to their on-page rects.
            try:
                for img in page.get_images(full=True):
                    xref = img[0]
                    for r in page.get_image_rects(xref):
                        asset = None
                        if export_figures:
                            asset = _export_figure(path, doc_id, pno + 1, xref, r)
                        add("figure", "", BBox(r.x0, r.y0, r.x1, r.y1), {"xref": xref}, asset)
            except Exception as e:
                warnings.append(f"{source} p{pno + 1}: figure detection failed ({e})")

            has_text = any(b.text.strip() and b.type != "figure" for b in blocks)
            # Tables are detected before text; restore document order by position
            # so headings stay attached to the content they introduce.
            blocks.sort(key=lambda b: ((b.bbox.y0, b.bbox.x0) if b.bbox else (1e9, 1e9)))
            blocks = [
                Block(f"{doc_id}:p{pno + 1}:{i:03d}", pno + 1, i, b.type, b.text, b.bbox, b.asset_path, dict(b.extra))
                for i, b in enumerate(blocks)
            ]
            pages.append(ParsedPage(pno + 1, page.rect.width, page.rect.height, tuple(blocks), has_text))
    finally:
        doc.close()
    return ParsedDocument(source, doc_id, "pymupdf", _pkg("pymupdf"), tuple(pages), tuple(warnings))


def _export_figure(path: Path, doc_id: str, page_no: int, xref: int, rect) -> str | None:
    import pymupdf as fitz

    outdir = ARTIFACT_DIR / doc_id / "figures"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"p{page_no}-x{xref}.png"
    if out.exists():
        return out.relative_to(ARTIFACT_DIR).as_posix()
    doc = fitz.open(path)
    try:
        pix = doc.extract_image(xref)
        out.write_bytes(pix["image"])
        return out.relative_to(ARTIFACT_DIR).as_posix()
    except Exception:
        return None
    finally:
        doc.close()


# --------------------------------------------------------------- docling ----

def _parse_docling(path: Path, source: str, doc_id: str, export_figures: bool) -> ParsedDocument:
    try:
        from docling.document_converter import DocumentConverter
        from docling_core.types.doc import ListItem, PictureItem, SectionHeaderItem, TableItem, TextItem
    except ImportError as e:
        raise ParseError(f"{source}: docling backend requested but not installed ({e}); pip install docling")
    try:
        res = DocumentConverter().convert(str(path))
    except Exception as e:
        raise ParseError(f"{source}: docling conversion failed ({type(e).__name__}: {e})")
    document = res.document
    by_page: dict[int, list] = {}
    order: dict[int, int] = {}

    def add(page_no: int, btype, text, bbox=None, extra=None, asset=None):
        i = order.get(page_no, 0)
        order[page_no] = i + 1
        by_page.setdefault(page_no, []).append(
            Block(f"{doc_id}:p{page_no}:{i:03d}", page_no, i, btype, text, bbox, asset, extra or {})
        )

    warnings: list[str] = []
    for item, _level in document.iterate_items():
        prov = item.prov[0] if getattr(item, "prov", None) else None
        if prov is None:
            warnings.append(f"{source}: item without page provenance skipped ({type(item).__name__})")
            continue
        page_no = prov.page_no
        coord = getattr(prov, "bbox", None)
        bbox = BBox(coord.l, coord.t, coord.r, coord.b) if coord is not None else None
        extra = {"coord_origin": "docling"}
        if isinstance(item, SectionHeaderItem):
            add(page_no, "heading", item.text, bbox, extra)
        elif isinstance(item, TableItem):
            grid = item.data.grid if item.data else []
            rows = [" | ".join("" if c is None else str(getattr(c, "text", c)).strip() for c in row) for row in grid]
            rows = [r for r in rows if r.strip(" |")]
            if not rows:
                warnings.append(f"{source} p{page_no}: table with no cells detected (possible false positive)")
                continue
            extra.update({"rows": len(rows)})
            add(page_no, "table", "\n".join(rows), bbox, extra)
        elif isinstance(item, PictureItem):
            asset = _export_docling_figure(document, item, doc_id, page_no) if export_figures else None
            add(page_no, "figure", "", bbox, extra, asset)
        elif isinstance(item, ListItem):
            add(page_no, "list", item.text, bbox, extra)
        elif isinstance(item, TextItem):
            btype = "caption" if CAPTION_RE.match(item.text.strip()) else "paragraph"
            add(page_no, btype, item.text, bbox, extra)
        else:
            warnings.append(f"{source} p{page_no}: unmapped item type {type(item).__name__}; text kept as paragraph")
            add(page_no, "paragraph", getattr(item, "text", ""), bbox, extra)

    pages: list[ParsedPage] = []
    for page_no in sorted(by_page):
        size = document.pages.get(page_no).size if document.pages and document.pages.get(page_no) else None
        blocks = by_page[page_no]
        has_text = any(b.text.strip() for b in blocks)
        pages.append(ParsedPage(page_no, size.width if size else 0.0, size.height if size else 0.0, tuple(blocks), has_text))
    if not pages:
        raise ParseError(f"{source}: docling returned no pages")
    return ParsedDocument(source, doc_id, "docling", _pkg("docling"), tuple(pages), tuple(warnings))


def _export_docling_figure(document, item, doc_id: str, page_no: int) -> str | None:
    outdir = ARTIFACT_DIR / doc_id / "figures"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"docling-p{page_no}-{item.self_ref.split('/')[-1]}.png"
    if out.exists():
        return out.relative_to(ARTIFACT_DIR).as_posix()
    try:
        image = item.get_image(document)
        if image is None:
            return None
        image.save(out)
        return out.relative_to(ARTIFACT_DIR).as_posix()
    except Exception:
        return None


# --------------------------------------------------------------- pypdf ------

def _parse_pypdf(path: Path, source: str, doc_id: str) -> ParsedDocument:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        raise ParseError(f"{source}: cannot open ({type(e).__name__}: {e})")
    pages: list[ParsedPage] = []
    warnings = [f"{source}: pypdf fallback in use — single text block per page, no bboxes/tables/figures"]
    for pno, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as e:
            raise ParseError(f"{source} p{pno + 1}: text extraction failed ({type(e).__name__}: {e})")
        blocks: list[Block] = []
        if text:
            blocks.append(Block(f"{doc_id}:p{pno + 1}:000", pno + 1, 0, "paragraph", text))
        try:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
        except Exception:
            w, h = 0.0, 0.0
        pages.append(ParsedPage(pno + 1, w, h, tuple(blocks), bool(text)))
    return ParsedDocument(source, doc_id, "pypdf", _pkg("pypdf"), tuple(pages), tuple(warnings))


# --------------------------------------------------------------- public -----

BACKENDS = ("pymupdf", "docling", "pypdf")


def parse_document(path: str | Path, backend: str = "auto", enable_ocr: bool = False, export_figures: bool = False) -> ParsedDocument:
    """Parse one document into stable records. Never returns silently-empty data
    for a file that failed to parse — failures raise ParseError naming file/page."""
    p = Path(path)
    if not p.is_file():
        raise ParseError(f"{p}: file not found")
    try:
        source = p.resolve().relative_to(RAW_DIR.resolve()).as_posix()
    except ValueError:
        source = p.name
    doc_id = _document_id(source)

    choice = backend
    if backend == "auto":
        choice = "pymupdf"
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            choice = "pypdf"
    if choice not in BACKENDS:
        raise ParseError(f"{source}: unknown backend {backend!r} (expected one of {BACKENDS})")

    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        text = p.read_text(encoding="utf-8", errors="ignore").strip()
        blocks = (Block(f"{doc_id}:p1:000", 1, 0, "paragraph", text),) if text else ()
        return ParsedDocument(source, doc_id, "text", "builtin", (ParsedPage(1, 0.0, 0.0, blocks, bool(text)),), ())
    if suffix not in (".pdf",):
        raise ParseError(f"{source}: unsupported suffix {suffix!r} (expected .pdf/.txt/.md)")

    # Docling is the only backend in this project configured for OCR. Its
    # evaluated default pipeline runs RapidOCR on scanned pages.
    if enable_ocr and backend in ("auto", "docling"):
        try:
            import docling  # noqa: F401
            return _parse_docling(p, source, doc_id, export_figures)
        except ImportError:
            if backend == "docling":
                raise ParseError(f"{source}: docling backend requested but not installed; pip install docling")
    if choice == "pymupdf":
        doc = _parse_pymupdf(p, source, doc_id, export_figures)
    elif choice == "docling":
        doc = _parse_docling(p, source, doc_id, export_figures)
    else:
        doc = _parse_pypdf(p, source, doc_id)
    if enable_ocr:
        doc = _apply_ocr(doc, p)
    # NOTE: genuinely empty results (e.g. scanned PDFs) are returned as-is with
    # no text blocks. Phase 2 replacement logic must treat "no blocks" as
    # "keep prior index data", never as "delete everything". See plan §Migration-3.
    return doc


def _apply_ocr(doc: ParsedDocument, path: Path) -> ParsedDocument:
    """OCR pages without a text layer. No OCR backend is bundled yet: record a
    per-page warning and leave prior data intact (never index empty records)."""
    if all(p.has_text_layer for p in doc.pages):
        return doc
    warnings = list(doc.warnings)
    for page in doc.pages:
        if not page.has_text_layer:
            warnings.append(f"{doc.source} p{page.number}: OCR requested but no OCR backend available; page left unindexed")
    return ParsedDocument(doc.source, doc.document_id, doc.parser_name, doc.parser_version, doc.pages, tuple(warnings))


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Inspect parsed structure of one document.")
    ap.add_argument("path")
    ap.add_argument("--backend", default="auto", choices=["auto", *BACKENDS])
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--export-figures", action="store_true")
    args = ap.parse_args()
    try:
        doc = parse_document(args.path, args.backend, args.ocr, args.export_figures)
    except ParseError as e:
        print(f"ParseError: {e}")
        return 1
    print(f"{doc.source}  parser={doc.parser_name} {doc.parser_version}  id={doc.document_id}")
    for page in doc.pages:
        print(f"  p{page.number} ({page.width:.0f}x{page.height:.0f}) text_layer={page.has_text_layer} blocks={len(page.blocks)}")
        for b in page.blocks:
            preview = b.text[:80].replace("\n", " ")
            extra = f" asset={b.asset_path}" if b.asset_path else ""
            print(f"    [{b.order:02d}] {b.type:9} {len(b.text):4}ch bbox={'yes' if b.bbox else 'no ':4}{extra} {preview}")
    for w in doc.warnings:
        print(f"  warn: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
