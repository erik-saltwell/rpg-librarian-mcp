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
