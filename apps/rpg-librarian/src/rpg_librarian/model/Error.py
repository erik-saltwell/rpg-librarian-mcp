from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from .core import ProcessingStage, ProcessingStageType, UTCDateTime, utc_now


class Error(SQLModel, table=True):
    """A transient per-file, per-stage failure: one row, overwritten on retry."""

    __tablename__ = "error"

    file_id: int = Field(
        sa_column=Column(
            ForeignKey("file.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    stage: ProcessingStage = Field(
        sa_column=Column(ProcessingStageType(length=32), primary_key=True),
    )
    error_text: str = Field(nullable=False)
    occurred_at: datetime = Field(
        default_factory=utc_now,
        sa_type=UTCDateTime,
        sa_column_kwargs={"onupdate": utc_now},
    )
