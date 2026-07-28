from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import TypeDecorator
from sqlmodel import String


class MediaType(StrEnum):
    audio = "audio"
    video = "video"
    image = "image"
    vector = "vector"
    pdf = "pdf"
    mesh = "mesh"
    text = "text"
    unknown = "unknown"


class TolerantMediaType(TypeDecorator[MediaType]):
    """Store MediaType as plain text; degrade unrecognized values to `unknown` on read.

    A row's stored value can be something that isn't a current MediaType
    member -- planted directly against the DB, or left over from a removed
    enum member. SQLAlchemy's native Enum type raises on such a value the
    moment the row is deserialized, which would crash every query that
    happens to load the row, including ones scoped to an unrelated part of
    the catalog. media_type is a classification hint, not identity-critical,
    so degrading to `unknown` is safe -- it also means normal reconciliation
    (e.g. update_catalog deleting rows whose file no longer exists) can
    still see and clean up such a row instead of being permanently blocked
    by it.
    """

    impl = String
    cache_ok = True

    def process_bind_param(
        self, value: MediaType | str | None, dialect: Any
    ) -> str | None:
        if value is None:
            return None
        return MediaType(value).value

    def process_result_value(self, value: str | None, dialect: Any) -> MediaType | None:
        if value is None:
            return None
        try:
            return MediaType(value)
        except ValueError:
            return MediaType.unknown
