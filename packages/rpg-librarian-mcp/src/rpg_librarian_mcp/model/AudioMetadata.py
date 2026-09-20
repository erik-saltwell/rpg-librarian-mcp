from __future__ import annotations

from sqlmodel import Field

from ..utils.pydantic_aliases import NonEmptyStr
from .core import EntryMetadataBase


class AudioMetadata(EntryMetadataBase, table=True):
    """Type-specific metadata for Entry rows where media_type == audio."""

    genre: NonEmptyStr | None = Field(default=None, nullable=True)
    duration_seconds: float | None = Field(default=None, nullable=True)
