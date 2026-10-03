from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, UniqueConstraint
from sqlmodel import Field

from .core import EntityBase, FolderOutcome, FolderOutcomeType, UTCDateTime, utc_now


class FolderJudgment(EntityBase, table=True):
    """What `find-packs` concluded about one folder, and on what evidence.

    One row per folder (`folder` is relative to its root; `""` is the root itself).
    `fingerprint` summarizes the folder's contents when it was judged: while it is
    unchanged the stored answer is reused and the folder is not asked about again.
    `details` holds outcome-specific data (a container's children to descend into, a
    mixed folder's conflicting decisions, a validation failure's problems). `pack_id`
    links the pack an answer formed, while that pack exists.
    """

    __tablename__ = "folder_judgment"
    __table_args__ = (UniqueConstraint("root_id", "folder"),)

    root_id: int = Field(foreign_key="root.id", index=True)
    folder: str = Field(nullable=False)
    fingerprint: str = Field(nullable=False)
    outcome: FolderOutcome = Field(
        sa_column=Column(FolderOutcomeType(length=16), nullable=False, index=True)
    )
    reason: str | None = Field(default=None, nullable=True)
    details: dict[str, Any] | None = Field(default=None, sa_type=JSON, nullable=True)
    evidence: dict[str, Any] | None = Field(default=None, sa_type=JSON, nullable=True)
    pack_id: int | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("pack.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    judged_at: datetime = Field(default_factory=utc_now, sa_type=UTCDateTime)
