from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, text
from sqlmodel import Field

from .core import EntityBase, UTCDateTime


class ReviewFlag(EntityBase, table=True):
    """The LLM's "defer rather than guess" queue on a file.

    Resolved flags are kept, not deleted, as a queryable decision history --
    unlike `Error`, which is a transient failure log. `resolved_at` and
    `resolution_note` stay null while a flag is open. The partial unique index
    enforces at most one *open* flag per file.
    """

    __tablename__ = "review_flag"
    __table_args__ = (
        Index(
            "ix_review_flag_open_file_id",
            "file_id",
            unique=True,
            sqlite_where=text("resolved_at IS NULL"),
        ),
    )

    file_id: int = Field(
        sa_column=Column(ForeignKey("file.id", ondelete="CASCADE"), nullable=False)
    )
    reason: str = Field(nullable=False)
    resolved_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    resolution_note: str | None = Field(default=None, nullable=True)
