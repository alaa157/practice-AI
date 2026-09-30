# Study RAG (local, free)

Retrieval over your PDFs/slides, queried via MCP (`study_search`).

## What to provide (to start for real)

1. **Your files** — drop PDFs / `.txt` / `.md` into `study_rag/data/raw/`.
   `.pptx`/`.docx` are skipped for now (export to PDF first). Subfolders are scanned recursively.
   Scanned PDFs with no text layer are reported as "no extractable text" (needs OCR — tell me if you hit this).
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

## MCP (what you chose)

`study_rag/server.py` (stdio, FastMCP `study_mcp`) exposes:
- `study_search` (query, top_k) — cited chunks
- `study_list_sources` — files + chunk counts
- `study_ingest_status` — chunk count / db path / model

Wire into Codex/Copilot/Claude as a local stdio MCP server with command
`python /workspaces/practice-AI/study_rag/server.py`.
