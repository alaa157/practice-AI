# Phase 5 decision: defer visual page retrieval (ColPali)

> Wrap-up addendum (2026-09-30): the failure analysis in §1 below was
> written when the set scored 7 HIT / 1 MISS / 1 PASS (q6 MISS). The
> current tree scores **8 HIT / 0 MISS / 1 PASS** — q6 now HITs via a
> figure record (page-image + RapidOCR labels on the scanned PDF, no OCR
> flag). The verdict is unchanged (still DEFER: still zero visual-caused
> failures, still OOM), only stronger — there is now not even an OCR-flag
> gap left on this question set.

## 1. Failure analysis (plan §Phase 5.1)

Baseline after Phases 1–4: 7 HIT / 1 MISS / 1 PASS. The single MISS (q6,
scanned notes) is an OCR-flag gap, not a visual-understanding gap. **Zero
failures are caused by visual layout, unlabeled shapes, spatial relationships,
or caption gaps on study-meaningful questions** (labels, sequences, table
facts all HIT, several via figure records: q5 figure d=0.311, q9 d=0.308).

Vision-only stress probes (`eval/visual_stress.json`, not scored): shape /
position / shape-existence questions retrieve the *right page* (lexical
overlap) but the index cannot supply the answer — those facts live only in
pixels. This is the honest boundary of the caption index. Note the mitigation
already exists: Phase 4's `study_inspect_asset` delivers the pixels to a
vision-capable answering agent, so page routing (which works) + inspection
covers these cases without a visual index.

## 2. Feasibility probe (time-boxed, this machine: 2 CPU, 7.8 GB RAM, no GPU)

- colpali-engine 0.3.18 has **no ColSmol**; smallest available is ColQwen2-2B.
- Side effect: install downgraded torch 2.14→2.13 (pipeline re-verified
  green after; probe packages since removed).
- ColQwen2 fp16 download: ~8 GB staged (`/tmp` redirect required — the 32 GB
  overlay sits at 84%). Process died at 87% weight-load, ~2 min in: OOM on
  7.8 GB RAM. No page was ever encoded; per-page CPU latency unmeasurable
  here (expected minutes/page for a 2B VLM).
- Projected ColQwen2 index: ~768 patch vectors × 128 dims ≈ 0.4 MB/page —
  fine. Weights + RAM + CPU latency are the walls, not index size.

## 3. Comparison (same corpus/queries; ColPali column measured where possible)

| Criterion | Caption-augmented text index (shipped) | ColPali/ColQwen2 visual index |
|---|---|---|
| Correct source/page top-4 | 7/8 answerable HIT; MISS is OCR-flag, not visual | No evidence of gain: v1–v3 stress probes need pixel *reading*, not page *matching* — ColPali retrieves pages, same as today |
| Diagram recall (labels/order) | q4/q5/q9 HIT via captions + OCR labels | Nothing to add: labels already indexed deterministically |
| Citation usefulness | Page-exact bundles + openable PNGs | Same pages/images; no new evidence to cite |
| Index size/memory | 9 records, KBs; 90 MB embed model | +~0.4 MB/page projected; +4–8 GB weights — **OOM here** |
| Ingest/query latency | ~23 s full ingest; ms queries | Minutes/page CPU encode projected; unmeasurable (OOM first) |
| Setup complexity | pip-only (+1 GB docling models, optional) | 8 GB download, /tmp redirect, torch downgrade, `num2words`-class extras |
| Offline use | Cached models work offline | Fresh-machine cold start downloads GBs |

## 4. Verdict: DEFER (do not adopt)

Per the plan's own gate ("adopt only if the measured gain justifies
model/runtime/storage costs"): no visual-caused failure exists to fix, and
the cheapest viable visual model OOMs this hardware. No visual model becomes
a dependency. Page images + metadata stay canonical evidence regardless.

## 5. Reopen triggers

- Real user materials show diagram questions failing for layout/spatial
  reasons (add them to `questions.json` with expected pages first).
- GPU or ≥16 GB RAM available: re-run this probe (ColQwen2 or ColSmol if
  packaged) and fill in the latency/recall columns before adopting.
- A sub-500 MB visual retriever with CPU-friendly encode appears: evaluate
  against v1–v3, which the caption index provably cannot answer from text.
