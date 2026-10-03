"""Clear failure rows: every error in the catalog, or just those of some stages.

An `Error` row records that a stage failed for an entry, and it is cleared when the
stage later succeeds. Clearing them by hand wipes the record only; nothing is retried
for you. `scan` retries an unchanged, already hashed file only while it has a scan-stage
error, so clearing those (`scan`, `metadata`, `text`) means `scan` leaves the file alone
until it changes (or is forced). `enrich` retries by missing results, not by error rows,
so a failed lookup is retried either way. `reorganize` errors (files it could not move)
are replaced by the next `reorganize`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from ..errors import UsageError
from ..model import Error, ProcessingStage


def _stages(names: list[str] | None) -> list[ProcessingStage]:
    valid = [stage.value for stage in ProcessingStage]
    unknown = [name for name in names or [] if name not in valid]
    if unknown:
        raise UsageError(f"Unknown stage(s) {unknown}. Stages: {valid}.")
    return [ProcessingStage(name) for name in dict.fromkeys(names or [])]


def clear_errors(session: Session, stages: list[str] | None = None) -> dict[str, Any]:
    """Delete the error rows (all, or only those of `stages`) and say how many."""
    chosen = _stages(stages)
    counts = select(col(Error.stage), func.count()).group_by(col(Error.stage))
    delete_rows = delete(Error)
    if chosen:
        counts = counts.where(col(Error.stage).in_(chosen))
        delete_rows = delete_rows.where(col(Error.stage).in_(chosen))
    by_stage = {str(stage): count for stage, count in session.exec(counts).all()}
    session.exec(delete_rows)
    return {
        "cleared": sum(by_stage.values()),
        "by_stage": dict(sorted(by_stage.items())),
        "stages": [stage.value for stage in chosen] or "all",
    }
