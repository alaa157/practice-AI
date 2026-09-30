"""Shared settings for the local RAG pipeline."""

import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW_DIR = BASE / "data" / "raw"
DB_DIR = BASE / "chroma_db"
COLLECTION = "study_notes"
EMBED_MODEL = os.environ.get("STUDY_RAG_EMBED_MODEL", "all-MiniLM-L6-v2")
CHUNK_SIZE = int(os.environ.get("STUDY_RAG_CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.environ.get("STUDY_RAG_CHUNK_OVERLAP", "150"))
if CHUNK_SIZE <= 0:
    raise ValueError("STUDY_RAG_CHUNK_SIZE must be greater than zero")
if CHUNK_OVERLAP < 0 or CHUNK_OVERLAP >= CHUNK_SIZE:
    raise ValueError("STUDY_RAG_CHUNK_OVERLAP must be nonnegative and smaller than chunk size")
# Token budget note: all-MiniLM-L6-v2 truncates at 256 tokens (~1000 chars).
# The 800-char default stays under that; longer chunks would be silently cut
# by the embedding model, so raise CHUNK_SIZE only with a longer-context model.
# Cosine distance; matches are omitted when the nearest result is farther away.
MAX_COSINE_DISTANCE = 0.65

# Index record layout version. Ingest refuses to mix schemas: collections
# stamped with another version require `ingest.py --reset` (full rebuild).
INDEX_SCHEMA_VERSION = 2

# --- Phase 1: structured extraction -------------------------------------------
# Parser backend for document_parser.parse_document: "auto", "pymupdf",
# "docling", "pypdf". "auto" picks pymupdf, or docling for PDFs when ENABLE_OCR.
PARSER_BACKEND = os.environ.get("STUDY_RAG_PARSER", "auto")
# OCR is an extraction feature for scanned pages (not diagram understanding).
# Docling is optional; without it, OCR requests record per-page warnings.
ENABLE_OCR = os.environ.get("STUDY_RAG_OCR", "0") == "1"
# Generated artifacts (figure exports, parser caches). Never the source folder.
ARTIFACT_DIR = BASE / "artifacts"

# --- Phase 3: figures -----------------------------------------------------------
# Figure extraction + indexing. VLM-generated descriptions are opt-in.
ENABLE_FIGURE_INDEX = os.environ.get("STUDY_RAG_FIGURES", "1") == "1"
# "extracted" (caption + OCR labels only) or "smolvlm2" (adds local VLM
# descriptions; ~1 min/figure on 2 CPUs, needs num2words + model download).
FIGURE_DESCRIBER = os.environ.get("STUDY_RAG_FIGURE_DESCRIBER", "extracted")
FIGURE_DPI = int(os.environ.get("STUDY_RAG_FIGURE_DPI", "150"))
FIGURE_MAX_DIM = int(os.environ.get("STUDY_RAG_FIGURE_MAX_DIM", "1600"))
FIGURE_MAX_FIGURES = int(os.environ.get("STUDY_RAG_FIGURE_MAX_FIGURES", "50"))
FIGURE_OCR_MIN_SCORE = float(os.environ.get("STUDY_RAG_FIGURE_OCR_SCORE", "0.5"))
