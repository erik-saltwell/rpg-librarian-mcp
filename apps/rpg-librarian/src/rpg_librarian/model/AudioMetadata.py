from __future__ import annotations

from sqlmodel import Field

from .core import FileMetadataBase


class AudioMetadata(FileMetadataBase, table=True):
    """Type-specific metadata for files where media_type == audio."""

    __tablename__ = "audio_metadata"

    genre: str | None = Field(default=None, nullable=True)
    duration_seconds: float | None = Field(default=None, nullable=True)
