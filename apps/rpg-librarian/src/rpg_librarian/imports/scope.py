"""The headless filing server permits judgments only on its manifest's files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt
from sqlmodel import col, select

from ..db import session_scope
from ..model import Entry, File

READ_TOOLS = {
    "review_backlog",
    "list_unfiled",
    "list_product_types",
    "list_product_lines",
    "report_entry",
    "report_product",
    "report_line",
    "report-pack",
    "describe_schema",
    "query",
}


def enforce(session, identities: list[int], manifest: Path) -> None:
    data = json.loads(manifest.read_text())
    allowed_files = set(data["file_ids"])
    allowed_entries = set(data.get("entry_ids", identities))
    for identity in identities:
        if identity not in allowed_entries:
            raise ToolError(
                "Entry is outside this importer session's selected entries."
            )
        entry = session.get(Entry, identity)
        if entry is None:
            raise ToolError("Entry no longer exists; refresh the worklist.")
        members = (
            {entry.file_id}
            if entry.file_id is not None
            else set(
                session.exec(
                    select(File.id).where(col(File.pack_id) == entry.pack_id)
                ).all()
            )
        )
        if not members or not members <= allowed_files:
            raise ToolError("Entry is outside this importer session's work scope.")


class ImportScopeMiddleware(Middleware):
    def __init__(self, catalog: Path, manifest: Path):
        self.catalog = catalog
        data = json.loads(manifest.read_text())
        if data["catalog"] != str(catalog):
            raise ValueError("Importer manifest belongs to a different catalog.")
        self.file_ids = set(data["file_ids"])

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        name = context.message.name
        if name in READ_TOOLS:
            return await call_next(context)
        arguments = context.message.arguments or {}
        if name == "view_file":
            identities = [arguments.get("entry_id")]
        elif name == "update_product":
            identities = arguments.get("entry_ids", [])
        else:
            raise ToolError(
                "This importer session permits scoped view_file reads "
                "and update_product writes only."
            )
        if not identities:
            raise ToolError("No entries were selected.")
        with session_scope(self.catalog, migrate=False) as session:
            for identity in identities:
                entry = session.get(Entry, identity)
                if entry is None:
                    raise ToolError("Entry no longer exists; refresh the worklist.")
                if entry.file_id is not None:
                    members = {entry.file_id}
                else:
                    members = set(
                        session.exec(
                            select(File.id).where(col(File.pack_id) == entry.pack_id)
                        ).all()
                    )
                if not members or not members <= self.file_ids:
                    raise ToolError(
                        "Entry is outside this importer session's work scope."
                    )
        return await call_next(context)


def install(mcp, catalog: Path) -> None:
    manifest = os.environ.get("RPG_LIBRARIAN_IMPORT_MANIFEST")
    if manifest:
        mcp.add_middleware(ImportScopeMiddleware(catalog, Path(manifest)))
