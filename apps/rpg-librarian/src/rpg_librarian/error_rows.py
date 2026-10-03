"""Per-entry, per-stage failure rows: overwritten on retry, cleared on success.

Keyed by entry, including failures of file-level stages (`scan`, `reorganize`). A file
in a pack has no entry: `scan` takes a failing member out of its pack first (see
`membership.own_entry`), and `reorganize` summarizes members' failures on the pack's
entry.
"""

from __future__ import annotations

from sqlmodel import Session

from .model import Error, ProcessingStage

_MAX_TEXT = 2000


def record_error(
    session: Session, entry_id: int, stage: ProcessingStage, error: Exception
) -> str:
    """Write (or overwrite) the error row and return its text."""
    text = f"{type(error).__name__}: {error}"[:_MAX_TEXT]
    row = session.get(Error, (entry_id, stage))
    if row is None:
        row = Error(entry_id=entry_id, stage=stage, error_text=text)
    else:
        row.error_text = text
    session.add(row)
    return text


def clear_error(session: Session, entry_id: int, stage: ProcessingStage) -> None:
    row = session.get(Error, (entry_id, stage))
    if row is not None:
        session.delete(row)
