"""Shared helpers for querying Entry rows by exact parent_path.

`ParentPathType.process_bind_param` rejects any path with fewer than two
parts (`model/core.py`), and that validation runs on *every* bind -- not
just inserts. A real Entry can never have a parent_path shallower than
that, so a lookup against a shallow path is a structural non-match, not a
query to run: skip the bind entirely rather than let it raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import select

from ..model import Entry

if TYPE_CHECKING:
    from sqlmodel import Session


def entries_by_parent(session: Session, parent_path: Path) -> list[Entry]:
    if len(parent_path.parts) < 2:
        return []
    return list(
        session.exec(select(Entry).where(Entry.parent_path == parent_path)).all()
    )


def entry_by_exact_path(
    session: Session, parent_path: Path, filename: str
) -> Entry | None:
    if len(parent_path.parts) < 2:
        return None
    return session.exec(
        select(Entry).where(
            Entry.parent_path == parent_path, Entry.filename == filename
        )
    ).first()


def entries_under(session: Session, relative_path: Path) -> list[Entry]:
    """Every Entry whose parent_path is `relative_path` or a descendant of it.

    A full-table load, filtered in Python via `is_relative_to` rather than a
    SQL `LIKE` prefix match -- `ParentPathType`'s trailing-slash
    normalization makes `LIKE` unreliable here, same reasoning as
    `entries_by_parent` above. Safe against a row with a value that doesn't
    round-trip cleanly (e.g. a media_type not in the MediaType enum) because
    `Entry.media_type` degrades such values to `MediaType.unknown` on read
    (`TolerantMediaType`, `model/MediaType.py`) instead of raising.
    """
    return [
        entry
        for entry in session.exec(select(Entry)).all()
        if entry.parent_path.is_relative_to(relative_path)
    ]
