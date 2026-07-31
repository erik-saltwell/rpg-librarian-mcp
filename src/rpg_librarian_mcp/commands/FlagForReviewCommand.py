from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, col, select

from ..catalog import Catalog
from ..model import Entry, ProcessingStage, ReviewFlag
from .UpdateBaseCommand import UpdateBaseCommand


class FlagForReviewCommand(UpdateBaseCommand):
    """Raise (or update) an open review flag on every entry resolved from
    `path`, all sharing the one `reason` given for this call.

    Every resolved entry is always in scope -- `should_process` is
    unconditionally true, since flagging isn't a staleness check the way
    other commands' re-processing decisions are.
    """

    def __init__(self, catalog: Catalog, reason: str, max_errors: int = 50) -> None:
        super().__init__(catalog, ProcessingStage.flag_for_review, max_errors)
        self.reason = reason

    def should_process(self, session: Session, entry: Entry) -> bool:
        return True

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        open_flag = session.exec(
            select(ReviewFlag).where(
                ReviewFlag.entry_id == entry.id, col(ReviewFlag.resolved_at).is_(None)
            )
        ).first()
        if open_flag is None:
            open_flag = ReviewFlag(entry_id=entry.id, reason=self.reason)
        else:
            open_flag.reason = self.reason
        session.add(open_flag)
