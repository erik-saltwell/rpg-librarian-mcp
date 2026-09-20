from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, col, select

from ..catalog import Catalog
from ..model import Entry, ProcessingStage, ReviewFlag
from ..model.core import utc_now
from .UpdateBaseCommand import UpdateBaseCommand


class ResolveReviewFlagCommand(UpdateBaseCommand):
    """Close the open review flag (if any) on every entry resolved from
    `path`, recording one shared `resolution_note`.

    Entries with no open flag are skipped, not errored -- resolving a
    directory only touches whichever of its entries actually have something
    open.
    """

    def __init__(
        self, catalog: Catalog, resolution_note: str, max_errors: int = 50
    ) -> None:
        super().__init__(catalog, ProcessingStage.resolve_review_flag, max_errors)
        self.resolution_note = resolution_note

    def _open_flag(self, session: Session, entry: Entry) -> ReviewFlag | None:
        return session.exec(
            select(ReviewFlag).where(
                ReviewFlag.entry_id == entry.id, col(ReviewFlag.resolved_at).is_(None)
            )
        ).first()

    def should_process(self, session: Session, entry: Entry) -> bool:
        return self._open_flag(session, entry) is not None

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        open_flag = self._open_flag(session, entry)
        if open_flag is None:
            raise ValueError(f"{entry.path} has no open review flag")
        open_flag.resolved_at = utc_now()
        open_flag.resolution_note = self.resolution_note
        session.add(open_flag)
