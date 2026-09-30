"""Query the local Chroma study-notes collection (Phase 4 evidence bundles)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from retrieval import format_bundle, no_evidence_message, search_evidence  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+", help="question / search query")
    ap.add_argument("-k", type=int, default=4)
    args = ap.parse_args()
    if args.k < 1:
        ap.error("-k must be at least 1")

    try:
        bundles, diagnostics = search_evidence(" ".join(args.question), top_k=args.k)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not bundles:
        print(no_evidence_message(" ".join(args.question), diagnostics))
        return 0
    for ev in bundles:
        for line in format_bundle(ev):
            print(line)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
