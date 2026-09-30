#!/usr/bin/env python3
"""MCP server for study-notes RAG (stdio transport, FastMCP).

Tools (prefixed study_ to avoid collisions):
  study_search         - semantic search; returns grouped evidence bundles
                         (source/page, content type, distance signal, assets)
  study_inspect_asset  - open one figure/page image by asset ID: metadata plus
                         the image itself for vision-capable clients
  study_list_sources   - list ingested source files + chunk counts
  study_ingest_status  - collection stats (count, db path)

Run:  python server.py   (stdio)
Test: npx @modelcontextprotocol/inspector -- python server.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image
from pydantic import BaseModel, ConfigDict, Field

from config import ARTIFACT_DIR, COLLECTION, DB_DIR, EMBED_MODEL
from retrieval import format_bundle, kind_label, no_evidence_message, search_evidence

mcp = FastMCP("study_mcp")
logger = logging.getLogger(__name__)


def _collection():
    from retrieval import open_collection

    return open_collection()


class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Natural-language question, e.g. 'mitosis phases'", min_length=2, max_length=500)
    top_k: int = Field(default=4, description="Evidence bundles to return (grouped by source/page, so fewer than raw chunks)", ge=1, le=10)


@mcp.tool(
    name="study_search",
    annotations={"title": "Search study notes", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def study_search(params: SearchInput) -> str:
    """Search ingested study notes and return grouped evidence bundles.

    Each bundle cites source + page range, states its content type (source
    text vs extracted/generated figure description), and carries a cosine
    distance labeled as a retrieval signal — never answer confidence. Figure
    bundles include a stable asset reference for study_inspect_asset.

    Args:
        params (SearchInput): query + top_k bundles.

    Returns:
        str: Markdown evidence bundles, or a "no sufficiently close evidence"
        message (report that instead of unsupported content).
    """
    try:
        bundles, diagnostics = search_evidence(params.query, top_k=params.top_k)
        if not bundles:
            return no_evidence_message(params.query, diagnostics)
        lines = [f"# Evidence for '{params.query}'", ""]
        for ev in bundles:
            pages = f"pp. {ev.page_start}–{ev.page_end}" if ev.page_start is not None else "page ?"
            lines.append(
                f"## {ev.source}, {pages} ({kind_label(ev)}, distance {ev.distance:.3f}; "
                "retrieval signal, not answer confidence)"
            )
            lines.extend(format_bundle(ev)[1:])
            lines.append("")
        return "\n".join(lines)
    except Exception:
        logger.exception("study_search failed")
        return "Search failed. Check the server log and confirm dependencies and collection configuration."


class InspectInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    asset_id: str = Field(..., description="Figure/page-image asset ID from a study_search bundle, e.g. 'ac4941f5073fa780-p4-100_0-200_0-400_0-500_0-106766c7'", min_length=3, max_length=64)


def _find_asset(asset_id: str) -> tuple[dict | None, Path | None]:
    """Resolve an asset across all figure manifests. Returns (entry, png_path)."""
    for manifest_path in sorted(ARTIFACT_DIR.glob("*/figures.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            continue
        if asset_id in manifest:
            entry = manifest[asset_id]
            png = manifest_path.parent / "figures" / f"{asset_id}.png"
            return entry, png
    return None, None


@mcp.tool(
    name="study_inspect_asset",
    annotations={"title": "Inspect figure image", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def study_inspect_asset(params: InspectInput) -> list:
    """Open one figure/page image for visual inspection (vision answer step).

    Returns the asset's metadata (source, page, extracted caption, OCR labels,
    whether any description is generated) plus the image itself for
    image-capable clients. The local path is included for same-machine
    clients; remote clients that cannot open local paths still receive the
    image content. Cite the image's source page, not the model output.

    Args:
        params (InspectInput): asset_id from a study_search bundle.

    Returns:
        list: [metadata markdown, image content] (image omitted with a clear
        note when the file is missing or the ID is unknown).
    """
    try:
        entry, png = _find_asset(params.asset_id)
        if entry is None:
            known = []
            for manifest_path in sorted(ARTIFACT_DIR.glob("*/figures.json")):
                try:
                    known.extend(json.loads(manifest_path.read_text()).keys())
                except Exception:
                    continue
            hint = f" Known IDs: {', '.join(sorted(known)[:20])}." if known else " No figure assets indexed yet."
            return [f"Unknown asset_id '{params.asset_id}'.{hint}"]
        meta = [
            f"# Asset {params.asset_id}",
            f"- source: {entry.get('source', 'unknown')}",
            f"- page: {entry.get('page', 'unknown')}",
            f"- kind: {entry.get('kind', 'figure')}",
            f"- caption (extracted): {entry.get('caption_extracted') or 'none'}",
            f"- printed labels (OCR): {', '.join(entry.get('ocr_labels') or []) or 'none'}",
        ]
        if entry.get("description"):
            meta.append(f"- description (GENERATED by {entry.get('describer')} {entry.get('prompt_version')}; verify against the image)")
        if png is None or not png.is_file():
            meta.append(f"- image file missing (expected at {png}); cannot display this asset.")
            return ["\n".join(meta)]
        meta.append(f"- local path: {png}")
        meta.append("Answer from the image + text above; cite the source page.")
        return ["\n".join(meta), Image(str(png))]
    except Exception:
        logger.exception("study_inspect_asset failed")
        return ["Could not inspect asset. Check the server log."]


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
