"""Local RAG ingest for uni study materials (Phases 2–3).

Pipeline:
  PDF/txt/md -> document_parser.parse_document -> page-aware text chunks
  (chunking.build_text_chunks) + figure records (figures.build_figure_records)
  -> embeddings -> Chroma

Safety rules (plan §Migration):
- Every source is fully parsed BEFORE any index write. A ParseError aborts
  the run with no changes; empty results keep prior index data.
- Re-ingestion upserts the new version, then deletes superseded chunk IDs.
- `--reset` rebuilds by upsert-then-sweep, never by wipe-first.
- Collections stamped with another INDEX_SCHEMA_VERSION are refused until
  rebuilt with --reset (no silent schema mixing).

Usage:
  python ingest.py            # incremental ingest of data/raw/
  python ingest.py --reset    # full rebuild (same safety guarantees)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from chunking import build_text_chunks
from config import (
    ARTIFACT_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION,
    DB_DIR,
    EMBED_MODEL,
    ENABLE_FIGURE_INDEX,
    ENABLE_OCR,
    FIGURE_DESCRIBER,
    FIGURE_DPI,
    FIGURE_MAX_DIM,
    FIGURE_MAX_FIGURES,
    FIGURE_OCR_MIN_SCORE,
    INDEX_SCHEMA_VERSION,
    PARSER_BACKEND,
    RAW_DIR,
)
from document_parser import ParseError, parse_document

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="rebuild all records (upsert-then-sweep, no wipe-first)")
    args = ap.parse_args()

    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except ImportError:
        print("Missing deps. Run: pip install -r requirements.txt")
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in RAW_DIR.rglob("*") if p.is_file() and not p.name.startswith("."))

    # Phase A: parse everything before touching the index.
    parsed: list = []  # (source, ParsedDocument)
    skipped: list[tuple[str, str]] = []
    empty_kept: list[str] = []
    for f in files:
        source = f.relative_to(RAW_DIR).as_posix()
        suffix = f.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            reason = "export to PDF first" if suffix in (".pptx", ".docx") else f"unsupported ({suffix})"
            skipped.append((source, reason))
            continue
        try:
            doc = parse_document(f, backend=PARSER_BACKEND, enable_ocr=ENABLE_OCR)
        except ParseError as e:
            print(f"ABORT: {e}\nNo index changes were made; prior data is intact.")
            return 1
        for w in doc.warnings:
            print(f"  [warn] {w}")
        bare_pages = [p.number for p in doc.pages if not any(b.text.strip() for b in p.blocks)]
        if bare_pages:
            print(f"  [note] {source}: pages without text: {bare_pages}")
        if not doc.text_blocks:
            if ENABLE_FIGURE_INDEX and suffix == ".pdf":
                print(f"  [note] {source}: no text blocks; continuing to figure indexing")
            else:
                print(f"  [keep] {source}: no indexable text (prior records, if any, kept)")
                empty_kept.append(source)
                continue
        parsed.append((source, doc))

    # Phase B: open collection, enforce schema/model compatibility.
    client = chromadb.PersistentClient(path=str(DB_DIR))
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    create_meta = {"embedding_model": EMBED_MODEL, "hnsw:space": "cosine", "index_schema": INDEX_SCHEMA_VERSION}
    col = client.get_or_create_collection(COLLECTION, embedding_function=ef, metadata=create_meta)
    stored_model = (col.metadata or {}).get("embedding_model")
    if stored_model and stored_model != EMBED_MODEL:
        print(f"Collection uses embedding model {stored_model!r}; configured model is {EMBED_MODEL!r}. Re-run with --reset to rebuild.")
        return 1
    stored_schema = (col.metadata or {}).get("index_schema", 1)  # pre-Phase-2 collections have no stamp (= schema 1)
    if stored_schema != INDEX_SCHEMA_VERSION:
        if col.count() == 0 or args.reset:
            pass  # empty collections are stamped below; --reset sweeps stale records after upsert
        else:
            print(f"Collection uses index schema {stored_schema}; code expects {INDEX_SCHEMA_VERSION}. Re-run with --reset to rebuild.")
            return 1
    # Phase C: build chunks, upsert per source, then delete superseded IDs.
    # Figure records (Phase 3) join the same per-source ID set, so the sweep
    # below covers text and figure records together.
    new_ids: set[str] = set()
    total_chunks = 0
    preserved_figure_ids: set[str] = set()
    for source, doc in parsed:
        chunks = build_text_chunks(doc, CHUNK_SIZE, CHUNK_OVERLAP)
        ids, documents, metas = [], [], []
        for idx, chunk in enumerate(chunks):
            cid = f"{doc.document_id}:t{idx:04d}"
            ids.append(cid)
            documents.append(chunk.text)
            metas.append({
                "source": source,
                "document_id": doc.document_id,
                "chunk_id": cid,
                "chunk": idx,
                "page_start": chunk.page,
                "page_end": chunk.page,
                "block_types": "+".join(chunk.block_types),
                "parser_name": doc.parser_name,
                "parser_version": doc.parser_version,
                "content_kind": "text",
                "index_schema": INDEX_SCHEMA_VERSION,
                "content_hash": _content_hash(chunk.text),
            })
        fig_records: list[tuple[str, dict]] = []
        figure_index_failed = False
        if ENABLE_FIGURE_INDEX and doc.source.lower().endswith(".pdf"):
            from figures import FigureBuildConfig, build_figure_records

            try:
                fig_records = build_figure_records(
                    doc, RAW_DIR / source, ARTIFACT_DIR,
                    FigureBuildConfig(describer=FIGURE_DESCRIBER, dpi=FIGURE_DPI,
                                      max_dim=FIGURE_MAX_DIM, max_figures=FIGURE_MAX_FIGURES,
                                      ocr_min_score=FIGURE_OCR_MIN_SCORE),
                )
            except Exception as e:
                # Figure failures must not break text indexing for this source.
                print(f"  [warn] {source}: figure indexing failed ({type(e).__name__}: {e}); text kept")
                figure_index_failed = True
        if not chunks and not fig_records and not figure_index_failed:
            print(f"  [keep] {source}: no indexable text or figure records (prior records kept)")
            empty_kept.append(source)
            continue
        for text, meta in fig_records:
            ids.append(meta["chunk_id"])
            documents.append(text)
            metas.append(meta)
        for j in range(0, len(ids), 64):
            col.upsert(ids=ids[j : j + 64], documents=documents[j : j + 64], metadatas=metas[j : j + 64])
        prior = col.get(where={"source": source}, include=["metadatas"])
        prior_ids = prior.get("ids", [])
        if figure_index_failed:
            preserved_figure_ids.update(
                record_id
                for record_id, meta in zip(prior_ids, prior.get("metadatas", []))
                if not chunks or (meta and meta.get("content_kind") == "figure_description")
            )
        obsolete = sorted(set(prior_ids) - set(ids) - preserved_figure_ids)
        if obsolete:
            col.delete(ids=obsolete)
        new_ids.update(ids)
        total_chunks += len(ids)
        fig_note = f" + {len(fig_records)} figure" if fig_records else ""
        print(f"  [ok] {source}: {len(chunks)} text chunks{fig_note} (parser={doc.parser_name})")

    if args.reset:
        # Sweep stale records (old schema, removed content) only after the
        # full successful upsert above — never wipe-first. Keep records for
        # present sources that produced no chunks, as in incremental ingest.
        current = col.get(include=[])
        retained_ids: set[str] = set()
        for source in set(empty_kept) | {source for source, _ in skipped}:
            prior = col.get(where={"source": source}, include=[])
            retained_ids.update(prior.get("ids", []))
        stale = sorted(set(current.get("ids", [])) - new_ids - retained_ids - preserved_figure_ids)
        if stale:
            col.delete(ids=stale)
            print(f"  [reset] removed {len(stale)} stale records")
    else:
        # Remove sources that no longer exist; empty-kept sources are excluded
        # so their prior records survive.
        indexed = col.get(include=["metadatas"])
        sources = {m.get("source") for m in indexed.get("metadatas", []) if m and m.get("source")}
        parsed_sources = {source for source, _ in parsed}
        for source in sorted(sources - parsed_sources - set(empty_kept)):
            col.delete(where={"source": source})
            print(f"  [rm] {source}: source deleted, records removed")

    # Stamp the schema only after indexing and cleanup complete. An interrupted
    # rebuild must remain recognizable as the old schema on the next run.
    stored_metadata = col.metadata or {}
    if (
        stored_metadata.get("embedding_model") != EMBED_MODEL
        or stored_metadata.get("index_schema") != INDEX_SCHEMA_VERSION
    ):
        metadata = {k: v for k, v in stored_metadata.items() if not k.startswith("hnsw:")}
        metadata.update({"embedding_model": EMBED_MODEL, "index_schema": INDEX_SCHEMA_VERSION})
        col.modify(metadata=metadata)

    if skipped:
        print(f"  [skip] {len(skipped)} unsupported file(s): " + ", ".join(f"{s} ({r})" for s, r in skipped))
    if not files:
        print(f"No files in {RAW_DIR}.")
    print(f"Done. {total_chunks} chunks from {len(parsed)} source(s) in collection '{COLLECTION}' ({col.count()} total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
