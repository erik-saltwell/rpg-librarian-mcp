from __future__ import annotations

from sqlmodel import Field

from .core import FileMetadataBase


class ImageMetadata(FileMetadataBase, table=True):
    """Type-specific metadata for files where media_type == image.

    `pixel_count` is `width * height`, kept so "find large images" is a simple
    indexed comparison.
    """

    __tablename__ = "image_metadata"

    width: int | None = Field(default=None, nullable=True)
    height: int | None = Field(default=None, nullable=True)
    has_alpha: bool | None = Field(default=None, nullable=True)
    pixel_count: int | None = Field(default=None, nullable=True, index=True)
