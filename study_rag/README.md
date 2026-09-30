# Study RAG (local, free)

Retrieval over your PDFs/slides, queried via MCP (`study_search`).

## What to provide (to start for real)

1. **Your files** — drop PDFs / `.txt` / `.md` into `study_rag/data/raw/`.
   `.pptx`/`.docx` are skipped for now (export to PDF first). Subfolders are scanned recursively.
   Scanned PDFs need `STUDY_RAG_OCR=1` (Docling + RapidOCR backend) for page text;
   printed figure labels are OCR'd during figure indexing regardless.
2. **Defaults:** `all-MiniLM-L6-v2` embeddings, Chroma persistent DB in
   `study_rag/chroma_db/`. Chunking is page-aware (Phase 2): a chunk never
   spans pages, headings travel with their content, tables become dedicated
   chunks, and every record carries source, page range, block types, parser
   provenance, and schema version. Chunk budget via `STUDY_RAG_CHUNK_SIZE` /
   `STUDY_RAG_CHUNK_OVERLAP` (defaults 800/150 chars; 800 chars sits under the
   model's 256-token truncation limit).
3. To use another sentence-transformers model, set `STUDY_RAG_EMBED_MODEL` for
   ingestion and querying. Changing models requires a full rebuild with `--reset`.
   Use subfolders such as `data/raw/biology/` and `data/raw/math/` to organize
   sources; paths are retained in citations.

## Workflow

```bash
pip install -r study_rag/requirements.txt
python study_rag/ingest.py            # ingest data/raw/
python study_rag/ingest.py --reset    # full re-ingest
python study_rag/query.py "mitosis phases" -k 4
```

Ingestion updates chunks for changed sources and removes chunks for deleted
sources. Search omits results when the nearest cosine distance exceeds the
configured cutoff in `config.py`; treat returned distances as a retrieval
signal, not as answer confidence.

## Structured parsing (Phase 1)

`document_parser.parse_document(path, backend="auto", enable_ocr=False)`
returns stable `models.ParsedDocument` records (pages, ordered blocks with
types, bboxes, provenance) — ingestion must depend on this interface, not on
parser libraries. Backends: `pymupdf` (default), `docling` (optional heavy
backend + OCR engine), `pypdf` (explicit fallback). Source PDFs are read-only;
figure exports go to `artifacts/<document_id>/` (git-ignored).

```bash
python document_parser.py data/raw/biology/cell_biology.pdf
python document_parser.py data/raw/biology/field_notes_scanned.pdf --ocr
STUDY_RAG_OCR=1 python document_parser.py data/raw/biology/field_notes_scanned.pdf
```

`ingest.py` uses this adapter and the page-aware chunker. With OCR enabled and
the automatic or Docling backend selected, Docling handles scanned pages;
other backends report OCR-unavailable pages explicitly. Backend decision log:
`eval/PARSER_EVALUATION.md`.

## Evaluation (Phase 0)

`eval/` holds a synthetic mini-corpus (`make_corpus.py`, see `CORPUS.md`), an
8-question set with expected evidence (`questions.json`), and a baseline runner:

```bash
python ingest.py --reset && python eval/baseline.py
```

Results and analysis: `eval/baseline_results.json`, `eval/BASELINE.md`.

## Figures (Phase 3)

PDF figures are exported to `artifacts/<document_id>/figures/` (git-ignored)
and indexed as `figure_description` records with source, page, asset ID, and
provenance. Captions and RapidOCR printed labels are stored as extracted
evidence; model descriptions (opt-in `STUDY_RAG_FIGURE_DESCRIBER=smolvlm2`)
are labeled GENERATED in records and in retrieval output. Pages with captions
but no isolatable figures fall back to whole-page image assets. Re-ingest
skips unchanged figures via the `figures.json` manifest. Flags:
`STUDY_RAG_FIGURES=0` disables figure indexing. VLM decision log:
`eval/VISION_EVALUATION.md`.

## Retrieval (Phase 4)

One embedding search covers text + figure records (`retrieval.search_evidence`,
shared by `query.py` and `server.py`). Candidates are grouped by source/page/
asset so overlapping chunks don't crowd out other evidence; each bundle cites
source + page range, states its content type (source text vs extracted/
GENERATED figure description), and labels cosine distance as a retrieval
signal, never confidence. Cutoffs are per-kind and configurable
(`STUDY_RAG_FIGURE_CUTOFF`, default 0.65); weak retrieval reports "no
sufficiently close evidence" with per-kind closest distances.

`study_rag/server.py` (stdio, FastMCP `study_mcp`) exposes:
- `study_search` (query, top_k) — grouped evidence bundles
- `study_inspect_asset` (asset_id) — figure/page-image metadata + image
  content for vision-capable clients (local path included for same-machine
  use; unknown IDs get a clear error listing known IDs)
- `study_list_sources` — files + chunk counts
- `study_ingest_status` — chunk count / db path / model

A vision-capable agent answers diagram questions by calling `study_search`,
then `study_inspect_asset`, then answering with citations to the source page —
retrieval and answering stay separate steps.

## MCP tools

`study_rag/server.py` (stdio, FastMCP `study_mcp`, command
`python /workspaces/practice-AI/study_rag/server.py`) exposes the four tools
listed above: `study_search`, `study_inspect_asset`, `study_list_sources`,
`study_ingest_status`.
