# Parser evaluation (Phase 1 decision log)

Environment: 2 CPU, 7.8 GB RAM, no GPU, torch CPU. Docling 2.131.0,
PyMuPDF 1.28.2. Corpus: `biology/cell_biology.pdf` (3 born-digital pages),
`biology/field_notes_scanned.pdf` (2 image-only pages).

## Docling (standard pipeline)

- Setup friction: failed at first with `ImportError: libGL.so.1` (opencv-python
  needs a system library absent here). Fixed with
  `pip uninstall opencv-python && pip install opencv-python-headless`.
- `cell_biology.pdf`: ~50 s wall (first run incl. model downloads). Headings
  with page+bbox, Table 1 with 6 data rows, captions found. One false positive:
  an empty 0-row "table" on p3 (flowchart boxes) — the adapter skips it with an
  explicit warning.
- `field_notes_scanned.pdf` (RapidOCR): ~56 s for 2 pages. Full text recovered
  with page numbers and heading detection ("POND FIELD TRIP - 12 MAY").
- First run downloads ~1 GB of models (layout, tableformer, RapidOCR) —
  network required; cold offline use is not possible.

## Decision

- **Default backend: PyMuPDF.** Instant, light, fully offline, no downloads.
  Covers headings, tables, captions, bboxes, and figure detection for
  born-digital PDFs. Selected via `backend="auto"` (`STUDY_RAG_PARSER`).
- **Docling: optional backend** (`--backend docling`) and the automatic engine
  for PDFs when `enable_ocr=True` (`STUDY_RAG_OCR=1`). It is the only OCR path;
  without it, OCR requests record per-page warnings and leave prior index data
  intact.
- **pypdf: explicit fallback only**, with a provenance warning on every parse
  (no bboxes/tables/figures). Same stable `document_id` as the other backends.
- `document_id` (sha256 of the `data/raw/`-relative path) is identical across
  backends, so Phase 2 can re-index without orphaning records.
