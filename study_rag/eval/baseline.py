#!/usr/bin/env python3
"""Eval runner: each question in questions.json against the live collection
through retrieval.search_evidence — the same grouped path query.py/server.py
ship (Phase 4). Raw per-chunk retrieval is no longer evaluated separately.

Usage (from study_rag/):  python eval/baseline.py [--k 4] [--out eval/baseline_results.json]

Verdicts:
  HIT   - an acceptable source (and page, when specified) is in the bundles
  MISS  - no acceptable evidence retrieved (or cutoffs filtered everything)
  PASS  - no-answer question correctly returned nothing
  FALSE_HIT - no-answer question returned something under the cutoffs
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from config import EMBED_MODEL, FIGURE_MAX_COSINE_DISTANCE, MAX_COSINE_DISTANCE  # noqa: E402
from retrieval import open_collection, search_evidence  # noqa: E402

EVAL = Path(__file__).resolve().parent


def verdict(question: dict, bundles: list) -> str:
    acceptable = question["acceptable"]
    if not acceptable:  # no-answer question
        return "PASS" if not bundles else "FALSE_HIT"
    if not bundles:
        return "MISS"
    for ev in bundles:
        for a in acceptable:
            if ev.source != a["source"]:
                continue
            if "page" in a:
                ps, pe = ev.page_start, ev.page_end
                if ps is None or not (ps <= a["page"] <= (pe if pe is not None else ps)):
                    continue
            return "HIT"
    return "MISS"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--out", default=str(EVAL / "baseline_results.json"))
    args = ap.parse_args()

    questions = json.loads((EVAL / "questions.json").read_text())
    col = open_collection()
    results = []
    for q in questions:
        bundles, diagnostics = search_evidence(q["query"], top_k=args.k, col=col)
        hits = [
            {"source": ev.source, "page_start": ev.page_start, "page_end": ev.page_end,
             "content_kind": ev.content_kind, "describer": ev.describer,
             "asset_id": ev.asset_id, "distance": ev.distance, "merged": ev.merged,
             "excerpt": ev.text[:300]}
            for ev in bundles
        ]
        results.append({"id": q["id"], "category": q["category"], "query": q["query"],
                        "acceptable": q["acceptable"], "verdict": verdict(q, bundles),
                        "hits": hits, "diagnostics": diagnostics.get("closest", {})})
    payload = {
        "meta": {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "embedding_model": EMBED_MODEL,
            "cutoffs": {"text": MAX_COSINE_DISTANCE, "figure_description": FIGURE_MAX_COSINE_DISTANCE},
            "top_k_bundles": args.k,
            "records_indexed": col.count(),
            "phase": 4,
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
