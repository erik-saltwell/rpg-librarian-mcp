from __future__ import annotations

from sqlmodel import Field

from .core import FileMetadataBase


class VideoMetadata(FileMetadataBase, table=True):
    """Type-specific metadata for files where media_type == video."""

    __tablename__ = "video_metadata"

    duration_seconds: float | None = Field(default=None, nullable=True)
    width: int | None = Field(default=None, nullable=True)
    height: int | None = Field(default=None, nullable=True)
    has_audio: bool | None = Field(default=None, nullable=True)
