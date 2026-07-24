from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum, auto

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel, String

from ..utils.pydantic_aliases import NonEmptyStr
from .core import utc_now


class ErrorStage(StrEnum):
    populate_file_data = auto()


class Error(SQLModel, table=True):
    entry_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("entry.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    stage: ErrorStage = Field(
        sa_column=Column(String, primary_key=True),
    )
    error_text: NonEmptyStr
    occurred_at: datetime = Field(
        default_factory=utc_now,
        sa_column_kwargs={"onupdate": utc_now},
    )
