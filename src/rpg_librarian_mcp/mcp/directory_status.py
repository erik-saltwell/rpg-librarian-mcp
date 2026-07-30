"""What's-left-to-do views: per-file and per-directory product-identification status."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import Session

from ..catalog import Catalog
from ..db import session_scope
from ..tools.entry_queries import entries_by_parent, entries_under
from ..tools.path_helper import walk_directories, walk_filesystem


def list_directory_entries(
    catalog: Catalog, path: Path, recursive: bool = False
) -> dict[str, object]:
    """Files in `path`, each showing whether a product has been identified.

    If `path` is itself a file, returns a single-entry listing for that file.
    """
    relative_path = catalog.to_relative(path)
    absolute_path = catalog.to_absolute(relative_path)

    # Entry.parent_path is keyed by directory, not by the entry's own path --
    # for a file target, entries must be looked up under its *parent*
    # directory, or the query for entries under "the file's path" (never a
    # real parent_path) always comes back empty.
    query_path = relative_path.parent if absolute_path.is_file() else relative_path

    with session_scope(catalog) as session:
        if recursive:
            entries = entries_under(session, query_path)
        else:
            entries = entries_by_parent(session, query_path)
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
    for entry in entries_under(session, relative_path):
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
    if limit < 1:
        raise ValueError(f"limit must be a positive integer, got {limit}")
    relative_path = catalog.to_relative(path)
    absolute_path = catalog.to_absolute(relative_path)
    if absolute_path.is_file():
        raise ValueError(f"{path} is a file, not a directory")
    effective_limit = min(limit, 1000)

    with session_scope(catalog) as session:
        scanned_counts = _grouped_counts_by_directory(session, relative_path)

    # A path can be legitimately summarized even if it's missing on disk --
    # the catalog may hold entries scanned before the directory was later
    # removed. Only reject a path neither on disk nor known to the catalog.
    if not absolute_path.exists() and not scanned_counts:
        raise ValueError(f"{path} does not exist")

    # Grouped keys come straight from stored parent_path values, which can
    # in principle include a depth-<2 path planted outside the app's own
    # write path (ParentPathType rejects such a value on any normal bind).
    # No real Entry's parent_path can be that shallow, so such a group is
    # never a legitimate directory row -- same depth>=2 filter as the
    # filesystem-walk candidates just below, for the same reason.
    candidate_dirs: set[Path] = {
        dir_path for dir_path in scanned_counts if len(dir_path.parts) >= 2
    }
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
        """Files in `path`, each showing whether a product has been identified.

        `path` must be an absolute path. If `path` is itself a file, returns
        a single-entry listing for that file.
        """
        return list_directory_entries(catalog, path, recursive)

    @mcp.tool(name="summarize_directories")
    def summarize_directories_tool(
        path: Path, include_complete: bool = False, limit: int = 100
    ) -> dict[str, object]:
        """Per-directory product-identification counts, recursively under `path`.

        `path` must be an absolute path to a directory.
        """
        return summarize_directories(catalog, path, include_complete, limit)
