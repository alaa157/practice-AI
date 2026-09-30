#!/usr/bin/env python3
"""MCP server for study-notes RAG (stdio transport, FastMCP).

Tools (prefixed study_ to avoid collisions):
  study_search         - semantic search over ingested notes, returns cited chunks
  study_list_sources   - list ingested source files + chunk counts
  study_ingest_status  - collection stats (count, db path)

Run:  python server.py   (stdio)
Test: npx @modelcontextprotocol/inspector -- python server.py
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from config import COLLECTION, DB_DIR, EMBED_MODEL, MAX_COSINE_DISTANCE

mcp = FastMCP("study_mcp")
logger = logging.getLogger(__name__)


def _collection():
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    client = chromadb.PersistentClient(path=str(DB_DIR))
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=ef)
    stored_model = (col.metadata or {}).get("embedding_model")
    if stored_model and stored_model != EMBED_MODEL:
        raise RuntimeError(f"Collection embedding model is {stored_model!r}; configured model is {EMBED_MODEL!r}. Re-ingest with --reset.")
    return col


class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Natural-language question, e.g. 'mitosis phases'", min_length=2, max_length=500)
    top_k: int = Field(default=4, description="Chunks to return", ge=1, le=10)


@mcp.tool(
    name="study_search",
    annotations={"title": "Search study notes", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def study_search(params: SearchInput) -> str:
    """Search ingested study notes and return cited chunks.

    Args:
        params (SearchInput): query + top_k.

    Returns:
        str: Markdown with one section per chunk: source file, chunk id, text.
        Returns "No notes ingested yet..." when the collection is empty.
    """
    try:
        col = _collection()
        if col.count() == 0:
            return "No notes ingested yet. Drop PDFs into study_rag/data/raw/ and run: python study_rag/ingest.py"
        res = col.query(query_texts=[params.query], n_results=params.top_k)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]
        if not docs:
            return f"No matches for '{params.query}'."
        results = [(d, m, distance) for d, m, distance in zip(docs, metas, distances) if distance <= MAX_COSINE_DISTANCE]
        if not results:
            return f"No sufficiently close matches for '{params.query}' (closest cosine distance: {distances[0]:.3f})."
        lines = [f"# Results for '{params.query}'", ""]
        for d, m, distance in results:
            page = f", pages {m['page_start']}–{m['page_end']}" if "page_start" in m else ""
            kind = ""
            if m.get("content_kind") == "figure_description":
                gen = "GENERATED" if str(m.get("describer", "")).startswith("vlm:") else "extracted"
                kind = f" [figure description, {gen}]"
            lines.append(f"## {m.get('source')}{page} (chunk {m.get('chunk')}, cosine distance {distance:.3f}){kind}")
            lines.append(d[:1500])
            if m.get("asset_path"):
                lines.append(f"Asset (open locally): {m['asset_path']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("study_search failed")
        return "Search failed. Check the server log and confirm dependencies and collection configuration."


@mcp.tool(
    name="study_list_sources",
    annotations={"title": "List ingested sources", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def study_list_sources() -> str:
    """List source files currently ingested and their chunk counts."""
    try:
        col = _collection()
        items = col.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for m in items.get("metadatas", []):
            counts[m.get("source", "?")] = counts.get(m.get("source", "?"), 0) + 1
        if not counts:
            return "No sources ingested yet."
        return "\n".join(f"- {s}: {c} chunks" for s, c in sorted(counts.items()))
    except Exception as e:
        logger.exception("study_list_sources failed")
        return "Could not list sources. Check the server log."


@mcp.tool(
    name="study_ingest_status",
    annotations={"title": "Ingest status", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def study_ingest_status() -> str:
    """Collection stats: chunk count, db path, embedding model."""
    try:
        col = _collection()
        return f"collection={COLLECTION} chunks={col.count()} db={DB_DIR} model={EMBED_MODEL}"
    except Exception as e:
        logger.exception("study_ingest_status failed")
        return "Could not read ingest status. Check the server log."


if __name__ == "__main__":
    mcp.run()
