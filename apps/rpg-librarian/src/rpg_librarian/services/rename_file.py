"""Rename one cataloged file: on disk, or in the catalog for a filed file.

A kept file whose place in its product is stored (`File.subpath`) is renamed in the
catalog only, and `reorganize` moves it; every other file is renamed on disk in its
current folder, with its catalog path kept in sync. The file is named by its entry id,
and only file entries can be renamed.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from ..entries import entries_with_files, file_entry_ids
from ..errors import UsageError
from ..model import Disposition, Entry, EntryType, File, Root


def _validated_name(new_name: str) -> str:
    """Require a basename, never a path or a special directory component."""
    name = new_name.strip()
    if not name:
        raise UsageError("new_name must not be empty")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise UsageError("new_name must be a filename, not a path")
    if "\x00" in name:
        raise UsageError("new_name contains a null byte")
    return name


def rename_file(session: Session, entry_id: int, new_name: str) -> dict[str, Any]:
    """Rename a file within its current folder, updating disk and catalog together."""
    found = entries_with_files(session, [entry_id]).get(entry_id)
    if found is None:
        raise UsageError(f"No entry with id {entry_id}")
    entry, file = found
    if entry.type is not EntryType.file or file is None:
        raise UsageError(
            f"Entry {entry_id} is a {entry.type.value} entry; only files can be renamed"
        )
    file_id = file.id
    root = session.get(Root, file.root_id)
    if root is None:  # Defensive: the foreign key should make this impossible.
        raise UsageError(f"Entry {entry_id} refers to missing root {file.root_id}")
    if file.missing_since is not None:
        raise UsageError(f"Entry {entry_id} is marked missing; scan its root first")

    name = _validated_name(new_name)
    if file.disposition is Disposition.keep and file.subpath is not None:
        return _rename_subpath(session, entry, file, name)
    old_relative = PurePosixPath(file.relative_path)
    new_relative = old_relative.with_name(name)
    if new_relative == old_relative:
        return {
            "entry_id": entry_id,
            "root_id": root.id,
            "old_relative_path": str(old_relative),
            "relative_path": str(new_relative),
            "renamed": False,
            "on_disk": True,
        }

    source = Path(root.path) / Path(*old_relative.parts)
    destination = Path(root.path) / Path(*new_relative.parts)
    if not source.is_file():
        raise UsageError(f"Cataloged file does not exist on disk: {source}")
    if destination.exists():
        raise UsageError(f"Destination already exists: {destination}")

    collision = session.exec(
        select(File)
        .where(col(File.root_id) == file.root_id)
        .where(col(File.relative_path) == str(new_relative))
        .where(col(File.id) != file_id)
    ).first()
    if collision is not None:
        assert collision.id is not None
        other = file_entry_ids(session, [collision.id]).get(collision.id)
        raise UsageError(
            f"Destination is already cataloged as entry {other}: {new_relative}"
        )

    # Flush first so ordinary catalog constraint failures happen before the disk move.
    file.relative_path = str(new_relative)
    session.add(file)
    try:
        session.flush()
    except IntegrityError as error:
        raise UsageError(f"Could not reserve catalog path {new_relative}") from error

    try:
        source.rename(destination)
        session.commit()
    except Exception:
        session.rollback()
        if destination.exists() and not source.exists():
            try:
                destination.rename(source)
            except OSError as rollback_error:
                raise RuntimeError(
                    "Rename failed and the disk rollback also failed; "
                    f"the file is at {destination} but the catalog still records "
                    f"{source}"
                ) from rollback_error
        raise

    return {
        "entry_id": entry_id,
        "root_id": root.id,
        "old_relative_path": str(old_relative),
        "relative_path": str(new_relative),
        "renamed": True,
        "on_disk": True,
    }


def _rename_subpath(
    session: Session, entry: Entry, file: File, name: str
) -> dict[str, Any]:
    """Change the filename in a kept file's stored subpath; `reorganize` moves it."""
    assert file.subpath is not None
    old = PurePosixPath(file.subpath)
    new = old.with_name(name)
    result = {
        "entry_id": entry.id,
        "root_id": file.root_id,
        "relative_path": file.relative_path,
        "old_subpath": str(old),
        "subpath": str(new),
    }
    if new == old:
        return {**result, "renamed": False, "on_disk": False}
    clash = next(
        (
            other_entry
            for other, other_entry in session.exec(
                select(File, Entry)
                .join(Entry, col(Entry.file_id) == col(File.id))
                .where(col(Entry.product_id) == entry.product_id)
                .where(col(File.disposition) == Disposition.keep)
                .where(col(File.id) != file.id)
            ).all()
            if other.subpath is not None
            and other.subpath.casefold() == str(new).casefold()
        ),
        None,
    )
    if clash is not None:
        raise UsageError(
            f"Entry {clash.id} of the same product is already at subpath {new}"
        )
    file.subpath = str(new)
    session.add(file)
    session.commit()
    return {
        **result,
        "renamed": True,
        "on_disk": False,
        "note": "Recorded in the catalog; run `reorganize` to rename the file.",
    }
