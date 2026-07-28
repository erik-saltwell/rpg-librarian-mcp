from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from pydantic import StringConstraints
from sqlalchemy import TypeDecorator
from sqlmodel import DateTime, Field, SQLModel, String


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate_parent_path(parent_path: Path) -> None:
    if parent_path.is_absolute():
        raise ValueError("parent_path must not be absolute")

    if ".." in parent_path.parts:
        raise ValueError("parent_path must remain inside the archive root")

    if len(parent_path.parts) < 2:
        raise ValueError(
            "parent_path must include a parent folder and a grandparent folder"
        )


def validate_filename(filename: str) -> None:
    if not filename:
        raise ValueError("filename must not be empty")

    if PurePosixPath(filename).name != filename:
        raise ValueError("filename must not contain path separators")

    if not PurePosixPath(filename).suffix:
        raise ValueError("filename must include an extension")


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


class ParentPathType(TypeDecorator[Path]):
    """Store a relative directory path as normalized POSIX text."""

    impl = String
    cache_ok = True

    def process_bind_param(
        self,
        value: Path | str | None,
        dialect: Any,
    ) -> str | None:
        if value is None:
            return None

        path = Path(value)
        validate_parent_path(path)
        return PurePosixPath(*path.parts).as_posix()

    def process_result_value(
        self,
        value: str | None,
        dialect: Any,
    ) -> Path | None:
        if value is None:
            return None

        return Path(PurePosixPath(value))


class EntityBase(SQLModel):
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
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


Sha256 = Annotated[
    str,
    StringConstraints(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        to_lower=True,
        strip_whitespace=True,
    ),
]
