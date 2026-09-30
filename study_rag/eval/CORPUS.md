# Phase 0 corpus manifest

Synthetic but representative mini-corpus for retrieval experiments.
Regenerate with `python eval/make_corpus.py` (needs `pip install reportlab pillow`;
those are eval-only dependencies and are intentionally **not** in `requirements.txt`).

| File | Type | Pages | Contents |
|---|---|---|---|
| `biology/cell_biology.pdf` | born-digital PDF (reportlab) | 4 | p1 prose (protein synthesis); p2 Table 1 (organelles); p3 Figure 1 caption + vector cell shapes, Figure 2 caption + flowchart boxes/arrows. Shape/label text inside the vector drawings is **not** extractable — only captions are. **p4: embedded raster diagram** (mitochondrion; labels outer/inner membrane, cristae, matrix exist ONLY in the image) + "Figure 3" caption with no label words. |
| `biology/field_notes_scanned.pdf` | image-only PDF (Pillow raster) | 2 | "Pond field trip" notes; `pypdf` extracts 0 chars. Pond-water fact: volvox colonies + duckweed. |
| `physics/thermodynamics.md` | Markdown | — | Zeroth/first law notes (control path). |
| `sample.txt` | plain text | — | Pre-existing photosynthesis/mitosis note (existing behavior). |

Total: 4 files, ~1.3 KB text, 4 indexed chunks (scanned PDF skipped).
