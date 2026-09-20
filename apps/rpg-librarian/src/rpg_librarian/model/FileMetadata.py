from __future__ import annotations

from sqlmodel import Field

from .core import FileMetadataBase


class FileMetadata(FileMetadataBase, table=True):
    """Generic metadata read from a file's own embedded properties, any media type."""

    __tablename__ = "file_metadata"

    title: str | None = Field(default=None, nullable=True)
    artist: str | None = Field(default=None, nullable=True)
    publisher: str | None = Field(default=None, nullable=True)
    copyright: str | None = Field(default=None, nullable=True)
