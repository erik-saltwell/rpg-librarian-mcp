"""move -- relocate a file or folder within the library, keeping the catalog in sync."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import Session

from ..catalog import Catalog
from ..db import session_scope
from ..observability import log_event_fields
from ..tools.entry_queries import entries_under, entry_by_exact_path


def _validate_destination_depth(
    destination_relative: Path, source_is_dir: bool
) -> None:
    """Reject destinations the model could never store an Entry under.

    A moved folder's direct children would get `parent_path ==
    destination_relative`, which requires depth >= 2. A moved file's entry
    gets `parent_path == destination_relative.parent`, same requirement one
    level up. Checked before any disk or DB change so a rejection never
    follows a completed rename.
    """
    if source_is_dir:
        if len(destination_relative.parts) < 2:
            raise ValueError(
                f"{destination_relative} is too shallow to hold cataloged files "
                "(need at least a parent and grandparent folder)"
            )
    elif len(destination_relative.parent.parts) < 2:
        raise ValueError(
            f"{destination_relative} is too shallow to be cataloged "
            "(need at least a parent and grandparent folder)"
        )


def _check_no_stale_catalog_collision(
    session: Session, destination_relative: Path, is_dir: bool
) -> None:
    """Reject a destination with leftover Entry rows, even if disk is clear.

    Disk/catalog drift (the condition update_catalog's deletion
    reconciliation exists to repair) can leave a stale Entry row at a path
    with no file. Writing over that row would violate Entry's
    UniqueConstraint("parent_path", "filename") at commit -- after the
    rename already happened. Checked up front alongside the depth and
    disk-existence checks, for the same reason.
    """
    if is_dir:
        if entries_under(session, destination_relative):
            raise ValueError(f"{destination_relative} already has cataloged entries")
    elif (
        entry_by_exact_path(
            session, destination_relative.parent, destination_relative.name
        )
        is not None
    ):
        raise ValueError(f"{destination_relative} already has a cataloged entry")


def move(catalog: Catalog, source: Path, destination: Path) -> dict[str, object]:
    """Move a file or folder to a new location, updating the catalog to match."""
    source_relative = catalog.to_relative(source)
    destination_relative = catalog.to_relative(destination)
    source_absolute = catalog.to_absolute(source_relative)
    destination_absolute = catalog.to_absolute(destination_relative)

    if not source_absolute.exists():
        raise ValueError(f"{source} does not exist")
    if destination_absolute.exists():
        raise ValueError(f"{destination} already exists")

    is_dir = source_absolute.is_dir()
    if is_dir and (
        destination_relative == source_relative
        or destination_relative.is_relative_to(source_relative)
    ):
        raise ValueError(
            f"{destination} is inside {source} -- cannot move a folder into "
            "its own subdirectory"
        )
    _validate_destination_depth(destination_relative, is_dir)

    with session_scope(catalog) as session:
        _check_no_stale_catalog_collision(session, destination_relative, is_dir)

        entries_updated = 0
        if is_dir:
            for entry in entries_under(session, source_relative):
                suffix = entry.parent_path.relative_to(source_relative)
                entry.parent_path = destination_relative / suffix
                session.add(entry)
                entries_updated += 1
        else:
            entry = entry_by_exact_path(
                session, source_relative.parent, source_relative.name
            )
            if entry is not None:
                entry.parent_path = destination_relative.parent
                entry.filename = destination_relative.name
                session.add(entry)
                entries_updated = 1

        destination_absolute.parent.mkdir(parents=True, exist_ok=True)
        source_absolute.rename(destination_absolute)
        session.commit()

    log_event_fields(
        kind="folder" if is_dir else "file", entries_updated=entries_updated
    )
    return {
        "source": str(source_relative),
        "destination": str(destination_relative),
        "kind": "folder" if is_dir else "file",
        "entries_updated": entries_updated,
    }


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="move")
    def move_tool(source: Path, destination: Path) -> dict[str, object]:
        """Move a file or folder to a new location, updating the catalog to match.

        `source` and `destination` must both be absolute paths.
        """
        return move(catalog, source, destination)
