from __future__ import annotations

from sqlmodel import Field

from .core import EntryMetadataBase


class VideoMetadata(EntryMetadataBase, table=True):
    """Type-specific metadata for Entry rows where media_type == video."""

    duration_seconds: float | None = Field(default=None, nullable=True)
    width: int | None = Field(default=None, nullable=True)
    height: int | None = Field(default=None, nullable=True)
    has_audio: bool | None = Field(default=None, nullable=True)
