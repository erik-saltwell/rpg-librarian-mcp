from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field

from ..utils.pydantic_aliases import NonEmptyStr
from .core import EntityBase, UTCDateTime


class ReviewFlag(EntityBase, table=True):
    """A human-review request on an Entry, raised when the LLM would rather
    defer a decision (can't identify a product, unsure between candidates,
    etc.) than guess.

    Resolved flags are kept, not deleted, as a queryable decision history --
    unlike `Error`, which is a transient per-stage failure log, this is a
    log of judgment calls. `resolved_at`/`resolution_note` stay null while a
    flag is open. The partial unique index enforces at most one *open* flag
    per entry -- reflagging an already-flagged entry should update the
    existing row's `reason`, not pile up duplicates.
    """

    __table_args__ = (
        Index(
            "ix_reviewflag_open_entry_id",
            "entry_id",
            unique=True,
            sqlite_where="resolved_at IS NULL",
        ),
    )

    entry_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("entry.id", ondelete="CASCADE"), nullable=False)
    )
    reason: NonEmptyStr
    resolved_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    resolution_note: NonEmptyStr | None = Field(default=None)
