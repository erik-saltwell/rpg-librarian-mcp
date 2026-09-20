"""list_review_items -- all open human-review flags, optionally scoped."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import col, select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry, ReviewFlag


def list_review_items(catalog: Catalog, path: Path | None = None) -> dict[str, object]:
    """All open review flags, optionally scoped to a directory subtree."""
    relative_path: Path | None = None
    if path is not None:
        relative_path = catalog.to_relative(path)
        if not catalog.to_absolute(relative_path).exists():
            raise ValueError(f"{path} does not exist")

    stmt = (
        select(ReviewFlag, Entry)
        .join(Entry)
        .where(col(ReviewFlag.resolved_at).is_(None))
    )

    with session_scope(catalog) as session:
        rows = session.exec(stmt).all()

    items = [
        {
            "path": str(entry.path),
            "reason": flag.reason,
            "flagged_at": flag.created_at.isoformat(),
        }
        for flag, entry in rows
        if relative_path is None
        or entry.path == relative_path
        or entry.parent_path.is_relative_to(relative_path)
    ]
    items.sort(key=lambda item: item["path"])

    return {"items": items, "count": len(items)}


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="list_review_items")
    def list_review_items_tool(path: Path | None = None) -> dict[str, object]:
        """All open review flags, optionally scoped to a directory subtree.

        `path`, if given, must be an absolute path.
        """
        return list_review_items(catalog, path)
