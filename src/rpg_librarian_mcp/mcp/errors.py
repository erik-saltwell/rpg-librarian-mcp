"""list_errors -- all recorded processing errors, optionally scoped."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry, Error
from ..model.Error import ErrorStage


def list_errors(
    catalog: Catalog, path: Path | None = None, stage: ErrorStage | None = None
) -> dict[str, object]:
    """All recorded errors, optionally scoped to a directory subtree or a stage."""
    relative_path = catalog.to_relative(path) if path is not None else None

    stmt = select(Error, Entry).join(Entry)
    if stage is not None:
        stmt = stmt.where(Error.stage == stage)

    with session_scope(catalog) as session:
        rows = session.exec(stmt).all()

    errors = [
        {
            "path": str(entry.path),
            "stage": error.stage,
            "error_text": error.error_text,
            "occurred_at": error.occurred_at.isoformat(),
        }
        for error, entry in rows
        if relative_path is None
        or entry.path == relative_path
        or entry.parent_path.is_relative_to(relative_path)
    ]
    errors.sort(key=lambda e: e["path"])

    return {"errors": errors, "count": len(errors)}


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="list_errors")
    def list_errors_tool(
        path: Path | None = None, stage: ErrorStage | None = None
    ) -> dict[str, object]:
        """All recorded errors, optionally scoped to a directory subtree or a stage."""
        return list_errors(catalog, path, stage)
