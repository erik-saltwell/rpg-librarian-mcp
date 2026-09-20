from __future__ import annotations

from sqlmodel import Field

from .core import EntryMetadataBase


class ImageMetadata(EntryMetadataBase, table=True):
    """Type-specific metadata for Entry rows where media_type == image."""

    width: int | None = Field(default=None, nullable=True)
    height: int | None = Field(default=None, nullable=True)
    has_alpha: bool | None = Field(default=None, nullable=True)
    pixel_count: int | None = Field(default=None, nullable=True)
