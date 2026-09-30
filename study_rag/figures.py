"""Figure extraction + diagram description records (Phase 3).

Two asset kinds (plan §Phase 3.1/3.7):
- figure:     an embedded image isolated from a page (bbox recorded).
- page_image: fallback for pages with caption blocks but no isolatable
              figures (e.g. vector-only drawings) — whole page rendered.

Every asset gets a stable asset_id (sha256 of PNG bytes), a local file under
ARTIFACT_DIR/<document_id>/figures/, and a manifest entry (figures.json) that
caches OCR labels + descriptions by (image_sha, describer, prompt_version), so
unchanged figures cost nothing on re-ingest. No base64 payloads in Chroma.

Provenance discipline (plan §Phase 3.4/3.5):
- Extracted caption text and OCR labels are recorded separately from
  model-generated descriptions, and records state which is which.
- Records carry content_kind="figure_description" plus a describer id, so
  retrieval can cite generated content as generated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from models import ParsedDocument

FIGURE_PROMPT_VERSION = "figdesc-v2"
FIGURE_PROMPT = (
    "Describe ONLY what is visibly printed in this diagram: figure type and topic, "
    "title, legible labels, entities and their relationships, and arrow directions. "
    "Say 'unreadable' for anything unclear. Do not add facts not visible in the image."
)

VLM_MODEL_ID = "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"
_vlm = None  # (processor, model), loaded once per process when requested


@dataclass
class FigureAsset:
    asset_id: str
    source: str
    page: int
    kind: str  # "figure" | "page_image"
    image_path: str  # relative to ARTIFACT_DIR
    image_sha: str
    bbox: tuple | None = None
    caption_extracted: str = ""
    ocr_labels: list = field(default_factory=list)
    ocr_engine: str = ""
    description: str = ""  # model-generated; "" when describer=extracted
    describer: str = "extracted"
    prompt_version: str = FIGURE_PROMPT_VERSION
    status: str = "ok"  # ok | ocr-unavailable | skipped-empty


@dataclass(frozen=True)
class FigureRecord:
    text: str
    asset: FigureAsset


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _manifest_path(doc_id: str, artifact_dir: Path) -> Path:
    return artifact_dir / doc_id / "figures.json"


def _load_manifest(doc_id: str, artifact_dir: Path) -> dict:
    p = _manifest_path(doc_id, artifact_dir)
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_manifest(doc_id: str, artifact_dir: Path, manifest: dict) -> None:
    p = _manifest_path(doc_id, artifact_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2))


_ocr_engine = None


def ocr_labels(image_path: Path, min_score: float) -> tuple[list[str], str]:
    """Printed labels inside a figure image. Returns (labels, engine_id).
    Missing rapidocr -> ([], 'unavailable') so callers degrade explicitly."""
    global _ocr_engine
    try:
        from rapidocr import RapidOCR
    except ImportError:
        return [], "unavailable"
    try:
        if _ocr_engine is None:
            _ocr_engine = RapidOCR()
        res = _ocr_engine(str(image_path))
        if not res or not res.txts:
            return [], "rapidocr"
        labels = [t.strip() for t, s in zip(res.txts, res.scores or []) if t and t.strip() and (s is None or s >= min_score)]
        return labels, "rapidocr"
    except Exception:
        return [], "rapidocr-error"


def _render_pixmap(page, clip=None, dpi: int = 150, max_dim: int = 1600) -> bytes:
    import pymupdf

    zoom = dpi / 72
    pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom))
    if max(pix.width, pix.height) > max_dim:
        zoom *= max_dim / max(pix.width, pix.height)
        pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")


def discover_figure_images(
    pdf_path: Path,
    doc: ParsedDocument,
    artifact_dir: Path,
    dpi: int = 150,
    max_dim: int = 1600,
    max_figures: int = 50,
) -> list[FigureAsset]:
    """Export figure/page-image assets. Source PDF opened read-only."""
    import pymupdf

    assets: list[FigureAsset] = []
    manifest = _load_manifest(doc.document_id, artifact_dir)
    outdir = artifact_dir / doc.document_id / "figures"
    outdir.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open(pdf_path)
    try:
        captions_by_page: dict[int, list[str]] = {}
        for block in doc.blocks:
            if block.type == "caption" and block.text.strip():
                captions_by_page.setdefault(block.page, []).append(block.text.strip())
        count = 0
        for page in pdf:
            if count >= max_figures:
                break
            rects = []
            for img in page.get_images(full=True):
                rects.extend(page.get_image_rects(img[0]))
            if rects:
                for r in rects:
                    if count >= max_figures:
                        break
                    png = _render_pixmap(page, clip=r, dpi=dpi, max_dim=max_dim)
                    assets.append(_register_asset(
                        manifest, outdir, artifact_dir, doc, page.number + 1, "figure", png,
                        bbox=(r.x0, r.y0, r.x1, r.y1), captions=captions_by_page.get(page.number + 1, [])))
                    count += 1
            elif captions_by_page.get(page.number + 1):
                # Captioned figures with no isolatable image (vector drawings):
                # fall back to a whole-page asset (plan §3.7).
                png = _render_pixmap(page, dpi=min(dpi, 100), max_dim=max_dim)
                assets.append(_register_asset(
                    manifest, outdir, artifact_dir, doc, page.number + 1, "page_image", png,
                    captions=captions_by_page.get(page.number + 1, [])))
                count += 1
    finally:
        pdf.close()
    _save_manifest(doc.document_id, artifact_dir, manifest)
    return assets


def _register_asset(manifest, outdir, artifact_dir, doc, page_no, kind, png, bbox=None, captions=None) -> FigureAsset:
    sha = _sha(png)
    bbox_key = "page" if bbox is None else "-".join(f"{coord:.1f}".replace(".", "_") for coord in bbox)
    asset_id = f"{doc.document_id}-p{page_no}-{bbox_key}-{sha[:8]}"
    rel = (outdir / f"{asset_id}.png").relative_to(artifact_dir).as_posix()
    (outdir / f"{asset_id}.png").write_bytes(png)
    entry = manifest.get(asset_id, {})
    if entry.get("image_sha") != sha:
        entry = {"image_sha": sha, "ocr_labels": None, "description": None}
    entry.update({
        "source": doc.source,
        "page": page_no,
        "bbox": list(bbox) if bbox is not None else None,
        "kind": kind,
        "caption_extracted": " ".join(captions or []),
    })
    manifest[asset_id] = entry
    return FigureAsset(asset_id, doc.source, page_no, kind, rel, sha, bbox,
                       caption_extracted=" ".join(captions or []))


def fill_ocr_labels(assets: list[FigureAsset], artifact_dir: Path, doc_id: str, min_score: float) -> None:
    """Run figure-label OCR, reusing manifest cache by image hash."""
    manifest = _load_manifest(doc_id, artifact_dir)
    dirty = False
    for asset in assets:
        entry = manifest.get(asset.asset_id, {})
        if entry.get("image_sha") == asset.image_sha and entry.get("ocr_labels") is not None:
            asset.ocr_labels = entry["ocr_labels"]
            asset.ocr_engine = entry.get("ocr_engine", "")
            asset.status = entry.get("status", "ok")
            continue
        labels, engine = ocr_labels(artifact_dir / asset.image_path, min_score)
        asset.ocr_labels = labels
        asset.ocr_engine = engine
        asset.status = "ok" if engine not in ("unavailable", "rapidocr-error") else "ocr-unavailable"
        entry.update({"image_sha": asset.image_sha, "ocr_labels": labels,
                      "ocr_engine": engine, "status": asset.status})
        manifest[asset.asset_id] = entry
        dirty = True
    if dirty:
        _save_manifest(doc_id, artifact_dir, manifest)


def generate_description(
    image_path: Path,
    context: str = "",
    model_id: str = VLM_MODEL_ID,
    max_tokens: int = 150,
) -> tuple[str, str]:
    """Local VLM description of one figure. Returns (text, describer_id).

    Raises RuntimeError when the model cannot run — callers treat VLM as
    opt-in and fall back to extracted-only records. Needs `num2words`
    (pip install num2words) for the SmolVLM processor.
    """
    global _vlm
    try:
        from transformers import AutoModelForImageTextToText, AutoProcessor
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(f"VLM dependencies missing ({e})")
    try:
        if _vlm is None:
            proc = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
            model = AutoModelForImageTextToText.from_pretrained(model_id, trust_remote_code=True, dtype="auto")
            _vlm = (proc, model)
        proc, model = _vlm
        img = Image.open(image_path).convert("RGB")
        prompt = FIGURE_PROMPT
        if context.strip():
            prompt += (
                "\nNearby extracted source text (context only; it is not visual evidence):\n"
                + context.strip()
                + "\nUse this only to clarify the topic or terminology. Describe only details visible in the image."
            )
        conv = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        inputs = proc(text=proc.apply_chat_template(conv, add_generation_prompt=True), images=[img], return_tensors="pt")
        out = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
        text = proc.batch_decode(out, skip_special_tokens=True)[0].split("Assistant:")[-1].strip()
        if not text:
            raise RuntimeError("VLM returned empty description")
        return text, f"vlm:{model_id.split('/')[-1].lower()}"
    except Exception as e:
        raise RuntimeError(f"VLM description failed ({type(e).__name__}: {e})")


@dataclass
class FigureBuildConfig:
    describer: str = "extracted"  # "extracted" | "smolvlm2"
    dpi: int = 150
    max_dim: int = 1600
    max_figures: int = 50
    ocr_min_score: float = 0.5
    prompt_version: str = FIGURE_PROMPT_VERSION


def build_figure_records(
    doc: ParsedDocument,
    pdf_path: Path,
    artifact_dir: Path,
    cfg: FigureBuildConfig,
) -> list[tuple[str, dict]]:
    """Full per-source figure pipeline. Returns (record_text, metadata) pairs.

    Never raises for content issues: per-asset problems are recorded in the
    manifest status and skipped. Caller (ingest) still guards the whole call
    so figure failures cannot break text indexing.
    """
    assets = discover_figure_images(pdf_path, doc, artifact_dir, cfg.dpi, cfg.max_dim, cfg.max_figures)
    if not assets:
        return []
    fill_ocr_labels(assets, artifact_dir, doc.document_id, cfg.ocr_min_score)
    manifest = _load_manifest(doc.document_id, artifact_dir)
    records: list[tuple[str, dict]] = []
    for idx, asset in enumerate(assets):
        entry = manifest.get(asset.asset_id, {})
        if cfg.describer == "smolvlm2" and not asset.description:
            cache_ok = (
                entry.get("image_sha") == asset.image_sha
                and entry.get("describer", "").startswith("vlm:")
                and entry.get("prompt_version") == cfg.prompt_version
                and entry.get("description")
            )
            if cache_ok:
                asset.description = entry["description"]
                asset.describer = entry["describer"]
            else:
                try:
                    heading, page_text = nearby_context(doc, asset.page)
                    source_context = "\n".join(
                        part for part in (heading, asset.caption_extracted, page_text[:1000]) if part
                    )
                    asset.description, asset.describer = generate_description(
                        artifact_dir / asset.image_path, context=source_context
                    )
                    entry.update({"image_sha": asset.image_sha, "description": asset.description,
                                  "describer": asset.describer, "prompt_version": cfg.prompt_version})
                    manifest[asset.asset_id] = entry
                    _save_manifest(doc.document_id, artifact_dir, manifest)
                except RuntimeError as e:
                    asset.status = f"description-failed: {e}"
        heading, page_text = nearby_context(doc, asset.page)
        text = build_record_text(asset, heading, page_text)
        if text is None:
            continue
        cid = f"{doc.document_id}:f{idx:03d}"
        meta = {
            "source": asset.source,
            "document_id": doc.document_id,
            "chunk_id": cid,
            "chunk": idx,
            "page_start": asset.page,
            "page_end": asset.page,
            "block_types": "figure",
            "parser_name": "figures",
            "parser_version": "1",
            "content_kind": "figure_description",
            "describer": asset.describer,
            "prompt_version": cfg.prompt_version,
            "asset_id": asset.asset_id,
            "asset_path": f"artifacts/{asset.image_path}",
            "index_schema": 2,
            "content_hash": _sha(text.encode()),
        }
        records.append((text, meta))
    return records


def build_record_text(asset: FigureAsset, heading: str, page_text: str) -> str | None:
    """Compose the indexed text. Returns None when there is nothing searchable
    (no caption, no labels, no description) — such assets stay image-only."""
    lines = [f"[Figure ({asset.kind}) from {asset.source} p{asset.page}]"]
    if asset.caption_extracted:
        lines.append(f"Caption (extracted, not generated): {asset.caption_extracted}")
    if asset.ocr_labels:
        lines.append(f"Printed labels (OCR via {asset.ocr_engine}, extracted, not generated): {', '.join(asset.ocr_labels)}")
    if asset.description:
        lines.append(f"Description (GENERATED by {asset.describer} {asset.prompt_version}; may be uncertain, verify against the image): {asset.description}")
    if heading or page_text:
        nearby = f"{heading} — {page_text[:300]}" if heading else page_text[:300]
        lines.append(f"Nearby page context: {nearby}")
    if len(lines) == 1:
        return None
    # Note: the openable asset path travels in record metadata (asset_path),
    # not in the embedded text — display layers render it from metadata.
    return "\n".join(lines)


def nearby_context(doc: ParsedDocument, page_no: int) -> tuple[str, str]:
    heading = ""
    texts = []
    for block in doc.blocks:
        if block.page != page_no:
            continue
        if block.type == "heading" and block.text.strip():
            heading = block.text.strip()
        elif block.type in ("paragraph", "caption", "list") and block.text.strip():
            texts.append(block.text.strip())
    return heading, " ".join(texts)
