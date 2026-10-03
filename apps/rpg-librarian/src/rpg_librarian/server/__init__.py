"""The FastMCP stdio server."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import fastmcp
from fastmcp import FastMCP

from ..db import upgrade
from ..errors import CatalogNotFoundError
from ..observability import configure_wide_event_logs
from .middleware import ToolCallLoggingMiddleware
from .tools import register_tools

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
You are filing incoming RPG files into an organized library. Product judgments are
recorded in the catalog; a person runs `reorganize` later to make the share match them.
The `rename-file` tool is the narrow exception: it immediately renames one file in its
current folder and updates the catalog to match.

Workflow: (1) list_product_types and list_product_lines to learn the vocabulary;
(2) list_unfiled to see the worklist, and pick a folder; (3) list_unfiled with that
folder to see its entries and their hints, and report_entry for anything unclear;
(4) update_product to file the folder's entries, many at once per product.

Every id the tools take or return for an item is an entry id (`entry_id`). An entry
is a file or a pack. A pack is a set of files with one collective identity (a map pack,
token set, audio or STL set) whose files have no identity of their own: it is filed as
a whole with one update_product call, and its members never appear on their own.
list_unfiled shows packs in their folder; report_entry summarizes one; report-pack
lists every member. Correct a pack's boundary with add-to-pack and remove-from-pack
(by path), or make one by hand with create-pack.

Rules: search list_product_lines before creating a line, and prefer existing types.
A product is a set of files that shipped together; standalone content (generic map
packs, sound effects) is its own product under a functional type, not under a game.
When you cannot tell, defer with update_product's review_flag rather than guessing.
Evidence (search results, ISBN records, the system guess) is a hint; the folder path
is often the best clue.
"""


def configure_logging() -> None:
    """Log to stderr only: stdout is the stdio transport's message channel."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_server(catalog_path: Path) -> FastMCP:
    """Build the server. Migrates the catalog once, so tool calls need not."""
    if not catalog_path.exists():
        raise CatalogNotFoundError(catalog_path)
    upgrade(catalog_path)
    configure_wide_event_logs(catalog_path)

    mcp = FastMCP(name="rpg-librarian", instructions=INSTRUCTIONS)
    mcp.add_middleware(ToolCallLoggingMiddleware())
    register_tools(mcp, catalog_path)
    log.info("catalog %s", catalog_path)
    return mcp


def run(catalog_path: Path) -> None:
    configure_logging()
    # A stdio server should not print a banner, and must not phone home at startup.
    fastmcp.settings.check_for_updates = "off"
    create_server(catalog_path).run(transport="stdio", show_banner=False)
