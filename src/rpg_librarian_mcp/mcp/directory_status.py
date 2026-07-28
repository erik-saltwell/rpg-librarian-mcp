"""What's-left-to-do views: per-file and per-directory product-identification status."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import Session, select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry
from ..tools.entry_queries import entries_by_parent
from ..tools.path_helper import walk_directories, walk_filesystem


def list_directory_entries(
    catalog: Catalog, path: Path, recursive: bool = False
) -> dict[str, object]:
    """Files in `path`, each showing whether a product has been identified."""
    relative_path = catalog.to_relative(path)
    absolute_path = catalog.to_absolute(relative_path)

    with session_scope(catalog) as session:
        if recursive:
            all_entries = session.exec(select(Entry)).all()
            entries = [
                entry
                for entry in all_entries
                if entry.parent_path.is_relative_to(relative_path)
            ]
        else:
            entries = entries_by_parent(session, relative_path)
        by_path = {entry.path: entry for entry in entries}

        files = []
        with_product = 0
        for file_path in walk_filesystem(absolute_path, recursive):
            file_relative = catalog.to_relative(file_path)
            entry = by_path.get(file_relative)
            has_product = entry is not None and entry.has_product
            if has_product:
                with_product += 1
            files.append(
                {
                    "filename": file_relative.name,
                    "media_type": entry.media_type if entry is not None else None,
                    "cataloged": entry is not None,
                    "has_product": has_product,
                }
            )

    return {
        "path": str(relative_path),
        "files": files,
        "count": len(files),
        "with_product": with_product,
        "without_product": len(files) - with_product,
    }


def _grouped_counts_by_directory(
    session: Session, relative_path: Path
) -> dict[Path, tuple[int, int]]:
    """parent_path -> (with_product, without_product) counts under relative_path."""
    counts: dict[Path, tuple[int, int]] = {}
    for entry in session.exec(select(Entry)).all():
        if not entry.parent_path.is_relative_to(relative_path):
            continue
        with_product, without_product = counts.get(entry.parent_path, (0, 0))
        if entry.has_product:
            with_product += 1
        else:
            without_product += 1
        counts[entry.parent_path] = (with_product, without_product)
    return counts


@dataclass
class _DirectoryRow:
    path: Path
    scanned: bool
    with_product: int
    without_product: int


def summarize_directories(
    catalog: Catalog,
    path: Path,
    include_complete: bool = False,
    limit: int = 100,
) -> dict[str, object]:
    """Per-directory product-identification counts, recursively under `path`."""
    relative_path = catalog.to_relative(path)
    absolute_path = catalog.to_absolute(relative_path)
    effective_limit = max(1, min(limit, 1000))

    with session_scope(catalog) as session:
        scanned_counts = _grouped_counts_by_directory(session, relative_path)

    candidate_dirs: set[Path] = set(scanned_counts)
    if len(relative_path.parts) >= 2:
        candidate_dirs.add(relative_path)
    if absolute_path.is_dir():
        for dir_path in walk_directories(absolute_path):
            dir_relative = catalog.to_relative(dir_path)
            if len(dir_relative.parts) >= 2:
                candidate_dirs.add(dir_relative)

    rows = []
    for dir_path in candidate_dirs:
        with_product, without_product = scanned_counts.get(dir_path, (0, 0))
        rows.append(
            _DirectoryRow(
                path=dir_path,
                scanned=dir_path in scanned_counts,
                with_product=with_product,
                without_product=without_product,
            )
        )

    if not include_complete:
        rows = [row for row in rows if not (row.scanned and row.without_product == 0)]

    rows.sort(key=lambda row: (-row.without_product, str(row.path)))

    total_directories = len(rows)
    truncated = total_directories > effective_limit
    rows = rows[:effective_limit]

    return {
        "path": str(relative_path),
        "directories": [
            {
                "path": str(row.path),
                "scanned": row.scanned,
                "with_product": row.with_product,
                "without_product": row.without_product,
            }
            for row in rows
        ],
        "total_directories": total_directories,
        "truncated": truncated,
    }


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="list_directory_entries")
    def list_directory_entries_tool(
        path: Path, recursive: bool = False
    ) -> dict[str, object]:
        """Files in `path`, each showing whether a product has been identified."""
        return list_directory_entries(catalog, path, recursive)

    @mcp.tool(name="summarize_directories")
    def summarize_directories_tool(
        path: Path, include_complete: bool = False, limit: int = 100
    ) -> dict[str, object]:
        """Per-directory product-identification counts, recursively under `path`."""
        return summarize_directories(catalog, path, include_complete, limit)
