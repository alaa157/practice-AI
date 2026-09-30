"""Shared retrieval over text + figure records (Phase 4).

One embedding search feeds both record kinds; candidates are grouped by
(source, page, asset) so overlapping chunks from a page don't crowd out other
evidence. Each bundle carries source/page, content type, the distance labeled
as a retrieval signal (never answer confidence), and a stable asset reference
when a figure/page image exists. Per-kind distance cutoffs are configurable;
weak retrieval is reported as "no sufficiently close evidence", never as an
answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config import (
    COLLECTION,
    DB_DIR,
    EMBED_MODEL,
    FIGURE_MAX_COSINE_DISTANCE,
    MAX_COSINE_DISTANCE,
    RETRIEVAL_CANDIDATE_MULT,
)


@dataclass
class Evidence:
    source: str
    page_start: int | None
    page_end: int | None
    content_kind: str  # "text" | "figure_description"
    describer: str  # "extracted" | "vlm:..." | "" for text
    asset_id: str | None
    asset_path: str | None
    text: str
    distance: float
    merged: int = 1  # records folded into this bundle (same page group)


def open_collection():
    """Shared Chroma opener. Raises RuntimeError on model mismatch."""
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    client = chromadb.PersistentClient(path=str(DB_DIR))
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=ef)
    stored_model = (col.metadata or {}).get("embedding_model")
    if stored_model and stored_model != EMBED_MODEL:
        raise RuntimeError(
            f"Collection embedding model is {stored_model!r}; configured model is {EMBED_MODEL!r}. "
            "Re-ingest with --reset."
        )
    return col


def _threshold_for(kind: str) -> float:
    return FIGURE_MAX_COSINE_DISTANCE if kind == "figure_description" else MAX_COSINE_DISTANCE


def search_evidence(query: str, top_k: int = 4, col=None) -> tuple[list[Evidence], dict]:
    """Returns (bundles, diagnostics). Bundles ranked by best distance."""
    if col is None:
        col = open_collection()
    total = col.count()
    if total == 0:
        return [], {"indexed": 0}
    n = max(top_k, min(total, top_k * RETRIEVAL_CANDIDATE_MULT))
    res = col.query(query_texts=[query], n_results=n)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    distances = res.get("distances", [[]])[0]

    diagnostics: dict = {"indexed": total, "candidates": len(docs), "closest": {}}
    groups: dict[tuple, Evidence] = {}
    for doc, meta, dist in zip(docs, metas, distances):
        kind = meta.get("content_kind", "text")
        prev = diagnostics["closest"].get(kind)
        if prev is None or dist < prev:
            diagnostics["closest"][kind] = round(float(dist), 4)
        if dist > _threshold_for(kind):
            continue
        key = (meta.get("source"), meta.get("page_start"), meta.get("page_end"), meta.get("asset_id") or "")
        ev = Evidence(
            source=meta.get("source", "?"),
            page_start=meta.get("page_start"),
            page_end=meta.get("page_end"),
            content_kind=kind,
            describer=meta.get("describer", ""),
            asset_id=meta.get("asset_id"),
            asset_path=meta.get("asset_path"),
            text=doc,
            distance=round(float(dist), 4),
        )
        if key in groups:
            grouped = groups[key]
            grouped.merged += 1
            evidence_parts = grouped.text.split("\n\n--- Additional same-page evidence ---\n\n")
            if doc and doc not in evidence_parts:
                grouped.text += "\n\n--- Additional same-page evidence ---\n\n" + doc
        else:
            groups[key] = ev
    bundles = sorted(groups.values(), key=lambda e: e.distance)[: max(top_k, 0)]
    diagnostics["cutoffs"] = {"text": MAX_COSINE_DISTANCE, "figure_description": FIGURE_MAX_COSINE_DISTANCE}
    return bundles, diagnostics


def kind_label(ev: Evidence) -> str:
    if ev.content_kind == "figure_description":
        gen = "GENERATED" if ev.describer.startswith("vlm:") else "extracted"
        return f"figure description, {gen}"
    return "source text"


def format_bundle(ev: Evidence, max_chars: int = 4000) -> list[str]:
    """Render one evidence bundle. Shared by CLI and MCP output."""
    pages = f"p{ev.page_start}–p{ev.page_end}" if ev.page_start is not None else "page ?"
    lines = [f"[{ev.source} {pages} | {kind_label(ev)} | distance {ev.distance:.3f} (retrieval signal, not confidence)]"]
    lines.append(ev.text[:max_chars])
    if ev.merged > 1:
        lines.append(f"(+{ev.merged - 1} more chunk(s) from the same page folded in)")
    if ev.asset_path:
        lines.append(f"Asset (open locally): {ev.asset_path}")
    return lines


def no_evidence_message(query: str, diagnostics: dict) -> str:
    if diagnostics.get("indexed", 0) == 0:
        return "No notes ingested yet. Drop PDFs into study_rag/data/raw/ and run: python study_rag/ingest.py"
    closest = ", ".join(f"{k} {v:.3f}" for k, v in sorted(diagnostics.get("closest", {}).items()))
    cutoffs = diagnostics.get("cutoffs", {})
    return (
        f"No sufficiently close evidence for '{query}'"
        + (f" (closest: {closest}; cutoffs: text {cutoffs.get('text')}, figure {cutoffs.get('figure_description')})." if closest else ".")
        + " This is a retrieval signal, not an answer — do not present unsupported content."
    )
