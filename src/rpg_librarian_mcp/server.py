from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import db
from .catalog_io import export_catalog, import_catalog
from .purge_errors import purge_errors as _purge_errors
from .sync import sync_catalog as _sync_catalog

mcp = FastMCP("rpg-librarian")


@mcp.tool()
def export_catalog_to_json(path: str) -> dict:
    """Export the current library's catalog (products, entries, per-media-type
    metadata, OCR text) to a JSON file at `path`, overwriting it if it already
    exists. The library is the directory this server was started in."""
    conn = db.connect()
    try:
        data = export_catalog(conn)
    finally:
        conn.close()

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "path": str(out_path),
        "products": len(data["products"]),
        "entries": len(data["entries"]),
    }


@mcp.tool()
def import_catalog_from_json(path: str) -> dict:
    """Import a catalog JSON file (as produced by export_catalog_to_json) at
    `path` into the current library's catalog database. Rows are upserted by
    id: a product/entry already present with a matching id is overwritten,
    everything else already in the database is left untouched."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    conn = db.connect()
    try:
        stats = import_catalog(conn, data)
    finally:
        conn.close()

    return {"products": stats.products, "entries": stats.entries}


@mcp.tool()
def sync_catalog() -> dict:
    """Walk the library (the directory this server was started in), add
    catalog entries for new files, refresh entries for files whose mtime has
    changed since the last sync, leave unchanged files untouched, and remove
    catalog entries for files that no longer exist on disk. Extracts
    media-type-specific metadata and universal identity fields from embedded
    file tags. Does not perform product association or OCR text extraction --
    those are separate tools. Also writes claude.md/agents.md at the library
    root if they don't already exist (never overwrites either). Safe to call
    with zero arguments on both a brand-new and an existing library; this is
    the bootstrap step and the ongoing reconciliation step."""
    conn = db.connect()
    try:
        stats = _sync_catalog(conn)
    finally:
        conn.close()
    return {
        "added": stats.added,
        "updated": stats.updated,
        "unchanged": stats.unchanged,
        "removed": stats.removed,
        "errored": stats.errored,
        "errors": stats.error_details,
        "docs_created": stats.docs_created,
    }


@mcp.tool()
def purge_errors() -> dict:
    """Delete every catalog entry that has one or more recorded errors, along
    with its media-type metadata and OCR text. Does not resync -- run
    sync_catalog afterwards to reprocess the now-missing files as new. Useful
    after fixing an extraction bug so previously-failed files get a fresh
    attempt instead of keeping their stale, error-flagged row forever."""
    conn = db.connect()
    try:
        stats = _purge_errors(conn)
    finally:
        conn.close()
    return {"removed": stats.removed, "removed_filepaths": stats.removed_filepaths}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
