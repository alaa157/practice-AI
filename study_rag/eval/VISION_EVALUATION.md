# Vision evaluation (Phase 3 describer decision)

Question: can a small local VLM generate trustworthy diagram descriptions on
this machine (2 CPU, 7.8 GB RAM, no GPU)? Model: SmolVLM2-256M
(`HuggingFaceTB/SmolVLM2-256M-Video-Instruct`, ~500 MB weights), CPU,
greedy, 150 new tokens, visible-content-only prompt (`FIGURE_PROMPT`).

## Findings (mitochondrion test figure, labels verified by RapidOCR)

- Cost: ~30 s model load (once per process), ~50 s inference per figure.
  Acceptable for tiny corpora, prohibitive at scale on this hardware.
- Setup: needs `pip install num2words` (SmolVLM processor) and a
  `transformers>=5` API (`AutoModelForImageTextToText`; the old
  `AutoModelForVision2Seq` name is gone).
- Quality: topic right, most labels recovered — but hallucinated details
  ("labeled with the letter O/I/M", positions swapped: "outer membrane at
  the bottom"), and missed "cristae" on one run — the single most
  discriminative label, which RapidOCR read perfectly and deterministically.
- The visible-content-only prompt did not prevent invention.

## Decision

- Default describer: `extracted` (parser captions + RapidOCR printed labels).
  Deterministic, fast, cached models, no invention.
- `smolvlm2` stays as an **opt-in** backend (`STUDY_RAG_FIGURE_DESCRIBER`):
  wired end-to-end (manifest cache by image+model+prompt, GENERATED labeling
  in records and retrieval display), but off by default. Revisit only with a
  stronger local model or GPU, measured against q9-style questions.
