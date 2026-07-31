"""find_duplicates -- entries sharing the same content hash (sha256)."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry
from ..tools.entry_queries import entries_under


def find_duplicates(catalog: Catalog, path: Path | None = None) -> dict[str, object]:
    """Entries whose sha256 matches at least one other entry, grouped by hash.

    `path`, if given, scopes the scan to that directory subtree (recursive);
    otherwise the whole library is scanned.
    """
    relative_path: Path | None = None
    if path is not None:
        relative_path = catalog.to_relative(path)
        absolute_path = catalog.to_absolute(relative_path)
        if not absolute_path.exists():
            raise ValueError(f"{path} does not exist")
        if absolute_path.is_file():
            raise ValueError(
                f"{path} is a file, not a directory -- a duplicate-scan scope "
                "must be a directory (a single file can't contain a duplicate "
                "of itself)"
            )

    with session_scope(catalog) as session:
        entries = (
            entries_under(session, relative_path)
            if relative_path is not None
            else session.exec(select(Entry)).all()
        )

    by_hash: dict[str, list[Entry]] = {}
    for entry in entries:
        by_hash.setdefault(entry.sha256, []).append(entry)

    duplicate_hashes = [sha256 for sha256, group in by_hash.items() if len(group) > 1]
    duplicate_hashes.sort(key=lambda sha256: (-len(by_hash[sha256]), sha256))

    groups = [
        {
            "sha256": sha256,
            "count": len(by_hash[sha256]),
            "entries": [
                {"path": str(entry.path), "has_product": entry.has_product}
                for entry in sorted(by_hash[sha256], key=lambda e: e.path)
            ],
        }
        for sha256 in duplicate_hashes
    ]

    return {
        "duplicate_groups": groups,
        "duplicate_group_count": len(groups),
        "duplicate_file_count": sum(
            len(by_hash[sha256]) for sha256 in duplicate_hashes
        ),
    }


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="find_duplicates")
    def find_duplicates_tool(path: Path | None = None) -> dict[str, object]:
        """Entries whose sha256 content hash matches at least one other
        entry, grouped by hash.

        `path`, if given, must be an absolute path to a directory and
        scopes the scan to that subtree (recursive); otherwise the whole
        library is scanned. Each group lists every entry sharing that hash,
        with `has_product` so an already-identified copy can be told apart
        from an unidentified one when deciding which to keep.
        """
        return find_duplicates(catalog, path)
