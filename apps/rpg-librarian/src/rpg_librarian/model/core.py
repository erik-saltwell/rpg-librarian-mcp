from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, TypeDecorator
from sqlmodel import DateTime, Field, SQLModel, String

from rpg_librarian_tools.files import MediaType

from .Disposition import Disposition
from .ProcessingStage import ProcessingStage
from .RootKind import RootKind


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store/retrieve datetimes as UTC-aware, regardless of SQLite's naive storage."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to UTCDateTime column")
        return value.astimezone(UTC).replace(tzinfo=None)  # store naive UTC

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)  # reattach UTC on the way out


class _EnumText(TypeDecorator[StrEnum]):
    """Store a StrEnum as plain text.

    Subclasses set `enum_class`, and optionally `fallback`: an unrecognized stored
    value then degrades to it on read instead of raising, so one stale row cannot
    crash every query that happens to load it. Each enum gets its own subclass so
    the type renders without arguments other than `length`; each subclass must set
    `cache_ok` itself, because SQLAlchemy does not inherit it.
    """

    impl = String
    cache_ok = True
    enum_class: type[StrEnum]
    fallback: StrEnum | None = None

    def __init__(self, length: int = 32) -> None:
        super().__init__(length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return self.enum_class(value).value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return self.enum_class(value)
        except ValueError:
            if self.fallback is None:
                raise
            return self.fallback


class DispositionType(_EnumText):
    cache_ok = True
    enum_class = Disposition


class RootKindType(_EnumText):
    cache_ok = True
    enum_class = RootKind


class ProcessingStageType(_EnumText):
    cache_ok = True
    enum_class = ProcessingStage


class MediaTypeType(_EnumText):
    """`media_type` is a classification hint, so an unknown value reads as `unknown`."""

    cache_ok = True
    enum_class = MediaType
    fallback = MediaType.unknown


class EntityBase(SQLModel):
    id: int | None = Field(default=None, primary_key=True)

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=UTCDateTime,
    )

    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=UTCDateTime,
        sa_column_kwargs={"onupdate": utc_now},
    )


class FileMetadataBase(SQLModel):
    """Base for per-file metadata tables, one row per file.

    `file_id` is the primary key: each table holds at most one row per file,
    upserted in place on re-scan.
    """

    file_id: int | None = Field(
        default=None,
        foreign_key="file.id",
        nullable=False,
        ondelete="CASCADE",
        primary_key=True,
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=UTCDateTime,
    )

    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=UTCDateTime,
        sa_column_kwargs={"onupdate": utc_now},
    )


class EvidenceBase(FileMetadataBase):
    """Base for per-source evidence tables: one row per file, per source.

    Evidence is candidate signal for the LLM, never an asserted identification. It
    records its provenance: the `query` that produced it and when it was fetched.
    A query that found nothing still gets a row (empty `results`), so the file is
    not queried again.
    """

    query: str = Field(nullable=False)
    results: list[dict[str, Any]] = Field(
        default_factory=list, sa_type=JSON, nullable=False
    )
    fetched_at: datetime = Field(default_factory=utc_now, sa_type=UTCDateTime)
