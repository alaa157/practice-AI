#!/usr/bin/env python3
"""Run the Phase 0 baseline: each question in questions.json against the live
Chroma collection, using the same retrieval settings as query.py/server.py.

Usage (from study_rag/):  python eval/baseline.py [--k 6] [--out eval/baseline_results.json]

Verdicts:
  HIT   - an acceptable source (and page, when specified) is in the results
  MISS  - no acceptable evidence retrieved (or threshold filtered everything)
  PASS  - no-answer question correctly returned nothing
  FALSE_HIT - no-answer question returned something under the threshold
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from config import COLLECTION, DB_DIR, EMBED_MODEL, MAX_COSINE_DISTANCE  # noqa: E402

EVAL = Path(__file__).resolve().parent


def retrieve(col, query: str, k: int):
    res = col.query(query_texts=[query], n_results=k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    distances = res.get("distances", [[]])[0]
    return [
        {
            "source": m.get("source"),
            "page_start": m.get("page_start"),
            "page_end": m.get("page_end"),
            "chunk": m.get("chunk"),
            "distance": round(float(d), 4),
            "excerpt": doc[:300],
        }
        for doc, m, d in zip(docs, metas, distances)
        if d <= MAX_COSINE_DISTANCE
    ]


def verdict(question: dict, hits: list[dict]) -> str:
    acceptable = question["acceptable"]
    if not acceptable:  # no-answer question
        return "PASS" if not hits else "FALSE_HIT"
    if not hits:
        return "MISS"
    for h in hits:
        for a in acceptable:
            if h["source"] != a["source"]:
                continue
            if "page" in a:
                ps, pe = h.get("page_start"), h.get("page_end")
                if ps is None or not (ps <= a["page"] <= (pe if pe is not None else ps)):
                    continue
            return "HIT"
    return "MISS"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--out", default=str(EVAL / "baseline_results.json"))
    args = ap.parse_args()

    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    questions = json.loads((EVAL / "questions.json").read_text())
    client = chromadb.PersistentClient(path=str(DB_DIR))
    col = client.get_or_create_collection(
        COLLECTION, embedding_function=SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    )
    results = []
    for q in questions:
        hits = retrieve(col, q["query"], args.k)
        results.append({"id": q["id"], "category": q["category"], "query": q["query"],
                        "acceptable": q["acceptable"], "verdict": verdict(q, hits), "hits": hits})
    payload = {
        "meta": {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "embedding_model": EMBED_MODEL,
            "max_cosine_distance": MAX_COSINE_DISTANCE,
            "top_k": args.k,
            "chunks_indexed": col.count(),
            "phase": 0,
        },
        "results": results,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    summary: dict[str, int] = {}
    for r in results:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
        top = f"{r['hits'][0]['source']} d={r['hits'][0]['distance']}" if r["hits"] else "none"
        print(f"{r['verdict']:9} {r['id']:28} top: {top}")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
