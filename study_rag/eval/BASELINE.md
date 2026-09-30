# Phase 0 baseline with Phase 2–3 follow-ups

The first table below records the Phase 0 baseline captured before parser and
chunking changes. Reproduce current results with
`python ingest.py --reset && python eval/baseline.py` (top-k=6,
`all-MiniLM-L6-v2`, cosine, cutoff 0.65). The checked-in
`baseline_results.json` contains the later Phase 2 run; its metadata labels it
accordingly. The original full Phase 0 hit list was not retained as JSON.

## Results

| ID | Category | Verdict | Top hit |
|---|---|---|---|
| q1-text-photosynthesis | text | HIT | sample.txt d=0.274 |
| q2-text-transcription | text | HIT | cell_biology.pdf pp.1–2 d=0.463 |
| q3-table-atp | table | HIT | cell_biology.pdf pp.1–2 d=0.388 |
| q4-diagram-labels | diagram-labels | HIT | cell_biology.pdf p.3 d=0.471 |
| q5-diagram-relation | diagram-relation | HIT | cell_biology.pdf p.3 d=0.529 |
| q6-scanned-volvox | scanned | MISS | none (file skipped at ingest) |
| q7-markdown-zeroth | text | HIT | thermodynamics.md d=0.247 |
| q8-no-answer | no-answer | PASS | correctly empty |

## Recorded shortcomings (motivation for Phases 1–4)

1. **Chunks cross page boundaries.** `cell_biology.pdf` (3 pages, ~970 chars) became
   2 chunks; chunk 0 spans pp.1–2, so q2/q3 citations read "pages 1–2" instead of
   the true page. Phase 2 (page-aware chunking) should fix this.
2. **Table answer buried in mixed chunk.** q3's top hit excerpt shows p1 prose;
   the ATP row sits later in the same chunk next to unrelated text. Table
   serialization (Phase 2) should keep row context together.
3. **Diagrams retrievable only via caption text.** q4/q5 pass because captions
   restate labels and order. The vector shapes/arrows themselves contribute zero
   indexable content — caption-less figures (common in real slides) would MISS.
   Phase 3 (figure descriptions) targets this.
4. **Scanned pages silently absent.** The scanned PDF is skipped with a console
   line and contributes nothing; a user gets "no matches" with no hint that OCR
   could help. Phase 1 OCR + failure reporting targets this.
5. **Threshold fragility.** q2's distractor (sample.txt) scored 0.641, just under
   the 0.65 cutoff — a global cutoff behaves unevenly across content types
   (revisit in Phase 4).
6. **Reset-then-crash wiped the index.** `ingest.py --reset` deleted the Chroma
   collection and then crashed in `col.modify()` (passing `hnsw:space` to
   `modify` is rejected: "Changing the distance function ... is not supported").
   Fixed by only backfilling `embedding_model` on modify. Lesson recorded for the
   Phase 1 safeguard: parse/index a source fully *before* deleting its prior
   records; `--reset` should not destroy data before new data is ready.

## Phase 2 re-run note

After page-aware chunking (schema 2), the same set scores 6 HIT / 1 MISS /
1 PASS with strictly better distances (q2 0.463→0.351, q4 0.471→0.261,
q5 0.529→0.335). The table question now hits a dedicated p2 table chunk with
the answer visible instead of p1 prose. Remaining MISS is the scanned PDF
(needs Phase 1 OCR flag / Phase 3 work); shortcomings 1–2 above are closed,
3–5 stand.

## Phase 3 re-run note

With figure records (schema unchanged), the set scores 7 HIT / 1 MISS /
1 PASS. New q9 ("cristae" exists only inside the p4 raster) HITs at d=0.308
via the figure record, which cites p4, labels itself extracted, and points at
the openable PNG. Shortcoming 3 is closed for labeled figures; caption-less
vector drawings (p3 flowchart shapes) remain discoverable only through
captions/page text. q6 still MISSes (scanned text needs the Phase 1 OCR flag).

## Practical constraints

- Machine: 2 CPU, 7.8 GB RAM, no GPU (torch CPU). Full `--reset` ingest of this
  corpus: ~15 s wall (~10 s embedding-model load, one-time per process).
- Offline operation **not verified**: first run downloads the embedding model
  from HF Hub; offline reuse of the cached model untested.
- Expected real corpus: unknown size (user materials pending); keep ingest
  incremental and bounded (the current code already upserts per-source).
- Caption models: SmolVLM2-256M evaluated locally (~50 s/figure, hallucinates
  details the OCR reads correctly) — see `eval/VISION_EVALUATION.md`. VLM
  descriptions stay opt-in (`STUDY_RAG_FIGURE_DESCRIBER`); default is extracted
  captions + OCR labels. No remote model is ever called.
