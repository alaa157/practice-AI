"""Query the local Chroma study-notes collection."""

from __future__ import annotations

import argparse
import sys
from config import COLLECTION, DB_DIR, EMBED_MODEL, MAX_COSINE_DISTANCE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+", help="question / search query")
    ap.add_argument("-k", type=int, default=4)
    args = ap.parse_args()

    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    client = chromadb.PersistentClient(path=str(DB_DIR))
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=ef)
    stored_model = (col.metadata or {}).get("embedding_model")
    if stored_model and stored_model != EMBED_MODEL:
        print(f"Collection uses {stored_model!r}, configured model is {EMBED_MODEL!r}. Re-ingest with --reset.", file=sys.stderr)
        return 1
    if args.k < 1:
        ap.error("-k must be at least 1")
    q = " ".join(args.question)
    res = col.query(query_texts=[q], n_results=args.k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    distances = res.get("distances", [[]])[0]
    if not docs:
        print("No results. Run ingest.py first.")
        return 0
    results = [(d, m, distance) for d, m, distance in zip(docs, metas, distances) if distance <= MAX_COSINE_DISTANCE]
    if not results:
        print(f"No sufficiently close matches (closest cosine distance: {distances[0]:.3f}).")
        return 0
    for d, m, distance in results:
        page = f" pages {m['page_start']}–{m['page_end']}" if "page_start" in m else ""
        kind = ""
        if m.get("content_kind") == "figure_description":
            gen = "GENERATED" if str(m.get("describer", "")).startswith("vlm:") else "extracted"
            kind = f" [figure description, {gen}]"
        print(f"--- [{m.get('source')}{page} chunk {m.get('chunk')} distance {distance:.3f}]{kind} ---")
        print(d[:1200])
        if m.get("asset_path"):
            print(f"Asset (open locally): {m['asset_path']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
