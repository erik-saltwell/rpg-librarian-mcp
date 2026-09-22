"""Rename one cataloged file on disk and keep its catalog path in sync."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from ..errors import UsageError
from ..model import File, Root


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


def rename_file(session: Session, file_id: int, new_name: str) -> dict[str, Any]:
    """Rename a file within its current folder, updating disk and catalog together."""
    file = session.get(File, file_id)
    if file is None:
        raise UsageError(f"No file with id {file_id}")
    root = session.get(Root, file.root_id)
    if root is None:  # Defensive: the foreign key should make this impossible.
        raise UsageError(f"File {file_id} refers to missing root {file.root_id}")
    if file.missing_since is not None:
        raise UsageError(f"File {file_id} is marked missing; scan its root first")

    name = _validated_name(new_name)
    old_relative = PurePosixPath(file.relative_path)
    new_relative = old_relative.with_name(name)
    if new_relative == old_relative:
        return {
            "file_id": file_id,
            "root_id": root.id,
            "old_relative_path": str(old_relative),
            "relative_path": str(new_relative),
            "renamed": False,
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
        raise UsageError(
            f"Destination is already cataloged as file {collision.id}: {new_relative}"
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
        "file_id": file_id,
        "root_id": root.id,
        "old_relative_path": str(old_relative),
        "relative_path": str(new_relative),
        "renamed": True,
    }
