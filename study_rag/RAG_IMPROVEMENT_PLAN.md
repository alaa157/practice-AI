# RAG Improvements: Structured PDFs and Diagrams

## Goal

Improve the local study RAG system so it can retrieve useful evidence from PDF text, tables, scanned pages, and diagrams, while preserving trustworthy page citations and keeping source documents local by default.

## Current baseline

- `ingest.py` extracts PDF text with `pypdf`, adds page markers, chunks by approximate character length, and writes text to one Chroma collection.
- `server.py` and `query.py` retrieve text chunks only.
- The current pipeline does not index images, understand diagram structure, or return a viewable page/image reference.
- The project is local-first and uses a persistent local Chroma database.

## Recommended approach

Implement this in stages. First improve document parsing and citations. Next add diagram descriptions to the existing text retrieval path. Only then consider visual page retrieval such as ColPali if evaluation shows that captions and nearby text are insufficient.

Do not make a vision model a mandatory dependency for basic ingestion or text search. Keep extraction, optional visual enrichment, and retrieval separable so users can still ingest and search documents when an optional model is unavailable.

## User-visible outcome

For a question about a diagram, the system should find the relevant page, return nearby textual context and a concise description of the figure, identify the source file and page, and provide a way to inspect the original page or extracted figure. It must distinguish extracted source text from generated descriptions.

## Phases

### Phase 0 — Establish a representative corpus and retrieval baseline

**Purpose:** Make later choices based on the actual materials and queries.

1. Select a small local corpus that includes:
   - born-digital PDFs with selectable text and diagrams;
   - at least one scanned or image-based PDF, if present in the real materials;
   - charts, labeled figures, flowcharts, and tables where available;
   - plain text or Markdown files to preserve existing behavior.
2. Prepare a small question set with expected source and page evidence. Include text-only questions, questions answered by diagram labels, and questions requiring relationships shown by arrows or spatial layout.
3. Record current results from `query.py` for those questions. Note missing pages, misleading chunks, and relevant diagrams that are not surfaced.
4. Record practical constraints: machine RAM/VRAM, acceptable ingest time, offline requirement, expected corpus size, and whether generated captions may use a remote model.

**Acceptance criteria:** The corpus and question set are small enough to use repeatedly, include the material types that matter, and each question has a source/page or a clear expected answer location. Baseline shortcomings are recorded before parser changes.

### Phase 1 — Introduce a structured document extraction layer

**Purpose:** Preserve layout and page structure instead of flattening a PDF into one text string.

1. Add a parser adapter so ingestion calls a stable project interface rather than importing a parser throughout the pipeline. Suggested interface:

   ```python
   parse_document(path) -> ParsedDocument
   ```

2. Represent parsed output with explicit records:
   - document source path relative to `data/raw/`;
   - pages with one-based page numbers;
   - ordered blocks on each page, each with a type such as heading, paragraph, table, caption, or figure;
   - text for text-bearing blocks;
   - optional bounding box and parser provenance;
   - optional local asset path for figures.
3. Evaluate Docling as the first parser candidate. Use its structured output and page metadata; enable OCR and image export only where needed. Keep `pypdf` as a lightweight fallback only if the adapter can make fallback behavior explicit and compatible.
4. Preserve source ordering and headings. Avoid converting the complete document to plain Markdown and then losing block/page provenance.
5. Treat OCR as an extraction feature for text embedded in scanned pages. Do not treat OCR output as visual understanding of a diagram.
6. Keep source PDFs read-only. Write generated artifacts to a dedicated ignored/cache directory, organized by a stable source identifier.

**Suggested files:** `document_parser.py`, `models.py` (or a small equivalent), `config.py`, `requirements.txt`, `.gitignore`, and `README.md`.

**Acceptance criteria:** A parsed PDF can be traversed page by page; text blocks and tables retain page references; figures can be associated with page numbers; scanned pages can use OCR when enabled; parser failures identify the file/page and do not silently replace valid indexed data with empty content.

### Phase 2 — Build page-aware text chunks

**Purpose:** Make the text index more useful and citations dependable before adding image retrieval.

1. Chunk within page/block structure where possible. Keep headings with the content they introduce. Avoid splitting tables into meaningless fragments; serialize a table with headers and row context or keep it as a dedicated block.
2. Keep chunk size and overlap configurable. Use a token-aware limit if the chosen embedding model has a known token limit; otherwise retain a documented character fallback.
3. Store metadata on every text chunk:
   - `source` (relative path);
   - stable `document_id` and `chunk_id`;
   - `page_start` and `page_end`;
   - `block_types` or equivalent;
   - `parser_name` and `parser_version` where available;
   - `content_kind=text` and an index/schema version.
4. Use deterministic IDs derived from source identity, page/block position, and content. During re-ingestion, upsert the new version and delete superseded chunk IDs only after successful parsing and indexing.
5. Keep source/page/chunk provenance with retrieved results so the MCP tool can cite it directly.

**Acceptance criteria:** Chunks do not cross unrelated document pages without recording a page range; headings and table context survive; source changes do not leave stale text chunks; citations point to the actual source page(s).

### Phase 3 — Extract figures and add diagram descriptions

**Purpose:** Make diagrams discoverable through text search while retaining the original visual evidence.

1. Export each relevant figure as a local image asset. Store a stable asset ID, source path, page number, and optional bounding box in metadata. Avoid storing large base64 image payloads in Chroma documents.
2. Generate one concise caption/description per figure. Prompt for visible content only:
   - figure type and topic;
   - printed title and legible labels;
   - entities/nodes and their relationships;
   - direction of arrows or sequence where visible;
   - uncertainty for unreadable or ambiguous details.
3. Include nearby heading, caption, and page text as context for the description, but tell the model not to invent details not visible in the image.
4. Clearly mark descriptions as generated. Preserve original extracted captions and OCR labels separately from model-generated descriptions.
5. Index figure description and extracted caption/labels as searchable text records, with `content_kind=figure_description` (or equivalent), `source`, `page`, and `asset_id` metadata.
6. Make figure description generation optional and configurable. Persist results by a hash of the image, prompt version, and model identifier so unchanged figures do not incur repeated work.
7. Handle image-heavy/scanned pages where a parser cannot isolate figures: render the page as a page image asset and associate it with the page record.

**Acceptance criteria:** A query for a diagram concept can retrieve its caption/description; results identify it as generated content and cite the page; the corresponding local image/page can be opened; unreadable labels are not represented as certain facts; rerunning ingestion does not regenerate unchanged captions unnecessarily.

### Phase 4 — Retrieve text and visual evidence together

**Purpose:** Return a compact, inspectable evidence bundle instead of unrelated chunks.

1. Start with the existing text embedding search over ordinary text chunks and figure-description records.
2. Retrieve candidates, then group or de-duplicate by source/page/asset so multiple overlapping chunks from one page do not crowd out other evidence.
3. Return for each result:
   - source and page range;
   - content type (source text, extracted caption/OCR, or generated figure description);
   - relevant text/description;
   - distance or ranking signal with a clear label that it is not answer confidence;
   - a stable asset reference when a page/figure image exists.
4. Add a page/figure inspection path to the MCP tool contract. Choose a transport-safe representation: for example, a local path only when the calling client can access the same machine, or an MCP image/resource response if supported by the server/client combination. Do not assume a local path is accessible to remote clients.
5. For a question requiring visual inspection, allow a vision-capable answer step to receive the retrieved page/figure image plus neighboring text. Keep this separate from retrieval and retain citations to the image's source page.
6. Revisit the fixed cosine-distance threshold using the baseline question set. A global cutoff may not behave equally across text and generated descriptions; make it configurable and report “no sufficiently close evidence” rather than confident unsupported content.

**Acceptance criteria:** Search can return both text and figure evidence; results do not claim that generated descriptions are original source text; citations include page numbers; missing image access is reported clearly; weak retrieval does not get presented as strong evidence.

### Phase 5 — Evaluate direct visual page retrieval only if needed

**Purpose:** Decide whether a dedicated visual retrieval index is worth its complexity.

1. Re-run the baseline questions after Phases 1–4. Identify failures specifically caused by visual layout, unlabeled shapes, spatial relationships, or information not captured in captions.
2. If these remain common, prototype page-image retrieval with a model such as ColPali on a held-out subset. Treat this as a separate retrieval backend, not as a replacement for structured text extraction.
3. Compare it against the caption-augmented text index on:
   - correct source/page in top-k;
   - diagram-specific recall;
   - citation usefulness;
   - index size and memory use;
   - ingestion and query latency;
   - setup complexity and offline availability.
4. Adopt it only if the measured gain justifies model/runtime/storage costs. Keep page images and metadata as the canonical evidence regardless of the retrieval backend.

**Acceptance criteria:** There is a documented comparison on the same queries and corpus. The project does not add a large visual model as a mandatory dependency without demonstrated retrieval improvement and a clear runtime plan.

## Data and index layout

Keep separate logical record kinds even if they initially share one Chroma collection:

| Record kind | Indexed content | Required provenance |
|---|---|---|
| Text chunk | Paragraphs, headings, table text | source, page range, chunk ID, parser/version |
| Figure description | Generated visual description plus extracted caption/labels | source, page, asset ID, description model/prompt version |
| Page image (optional later) | Rendered page or visual embedding | source, page, image hash, visual model/version |

Generated image and parser artifacts should be derived data, never the only copy of evidence. Store them outside the source folder and exclude the artifact/cache directory from version control unless the project explicitly chooses to share it.

## Configuration decisions

Use explicit settings rather than hidden defaults for:

- parser selection and OCR enablement/languages;
- figure extraction and caption generation enablement;
- local vs remote caption model and its identifier;
- artifact/cache directory;
- text chunk limits;
- retrieval candidate count and per-record-type limits;
- text and visual distance/ranking thresholds;
- maximum rendered page resolution and image size;
- index/schema version.

Default to local processing where practical. If a remote vision model is enabled, make the data transfer explicit in configuration and documentation.

## Migration and operational safeguards

1. Add an index schema version and parser/model provenance to collection or record metadata.
2. Do not mix old and new records without a migration check. Provide a clear rebuild command and report which parser/model produced the index.
3. Parse and prepare a source successfully before deleting its prior records. A failed parse must leave the prior indexed version intact.
4. Ensure reset/rebuild targets only this application's collection and generated artifact directory.
5. Report skipped files, pages with no text, OCR failures, figure extraction failures, and model failures with source/page context.
6. Bound OCR, image rendering, and vision-caption work to avoid unbounded memory and runtime on large PDFs.

## Retrieval quality checks

Maintain a compact, version-controlled evaluation manifest containing queries and expected evidence locations, not private source documents. Include at least:

- text question answered by a paragraph;
- table lookup question;
- diagram question answered by labels;
- diagram question requiring relationships/arrows;
- scanned-page question if scans are in scope;
- question with no answer in the corpus.

For each change, review whether the correct source/page appears in the top results, whether the returned evidence supports the query, whether citations identify generated content, and whether no-answer queries avoid fabricated evidence. Do not treat embedding similarity alone as answer correctness.

## Implementation order for an AI coding agent

1. Read `README.md`, `config.py`, `ingest.py`, `query.py`, and `server.py`; inspect current Chroma APIs and the installed Python version before choosing a parser integration.
2. Implement Phase 1's parsed-document interface and parser adapter. Keep changes to one vertical slice: parse one PDF and expose page/block data without changing MCP output yet.
3. Implement Phase 2's page-aware text records and safe per-source replacement.
4. Implement Phase 3 behind an explicit configuration flag. Keep generated descriptions distinguishable from extracted text.
5. Update MCP/CLI output in Phase 4 to expose content kind, page citations, and image inspection references.
6. Use the Phase 0 question set to decide whether Phase 5 is justified; do not add ColPali by default.
7. Update README with dependencies, model downloads, local storage locations, offline behavior, and exact ingest/query commands.

### Agent guardrails

- Preserve the existing CLI and MCP tool names unless a documented compatibility reason requires a change.
- Keep the default pipeline usable without a vision model.
- Do not silently upload source pages to a remote service.
- Do not treat OCR or a generated caption as ground truth; preserve provenance and uncertainty.
- Do not drop page/source metadata during chunking, embedding, deduplication, or result formatting.
- Avoid broad refactors unrelated to document parsing, visual evidence, retrieval, and citations.
- Report unresolved runtime/model tradeoffs instead of choosing silently.

## References

- [Docling documentation](https://docling-project.github.io/docling/): structured document conversion, OCR, tables, figures, and chunking.
- [Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/): OCR and figure image extraction options.
- [PyMuPDF OCR guide](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html): local OCR for image-based page text; OCR does not interpret diagrams.
- [ColPali paper](https://arxiv.org/abs/2407.01449): page-image visual document retrieval as an optional later experiment.
- [Chroma documentation](https://docs.trychroma.com/): local vector storage, metadata filtering, and multimodal retrieval capabilities.
