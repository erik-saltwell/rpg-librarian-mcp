"""Per-file, per-stage failure rows: overwritten on retry, cleared on success."""

from __future__ import annotations

from sqlmodel import Session

from .model import Error, ProcessingStage

_MAX_TEXT = 2000


def record_error(
    session: Session, file_id: int, stage: ProcessingStage, error: Exception
) -> str:
    """Write (or overwrite) the error row and return its text."""
    text = f"{type(error).__name__}: {error}"[:_MAX_TEXT]
    row = session.get(Error, (file_id, stage))
    if row is None:
        row = Error(file_id=file_id, stage=stage, error_text=text)
    else:
        row.error_text = text
    session.add(row)
    return text


def clear_error(session: Session, file_id: int, stage: ProcessingStage) -> None:
    row = session.get(Error, (file_id, stage))
    if row is not None:
        session.delete(row)
