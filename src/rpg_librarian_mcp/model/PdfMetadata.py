from __future__ import annotations

from sqlmodel import Field

from .core import EntryMetadataBase


class PdfMetadata(EntryMetadataBase, table=True):
    """Type-specific metadata for Entry rows where media_type == pdf."""

    page_count: int | None = Field(default=None, nullable=True)
    is_encrypted: bool | None = Field(default=None, nullable=True)
    needs_password: bool | None = Field(default=None, nullable=True)
    has_extractable_text: bool | None = Field(default=None, nullable=True)
    likely_scanned: bool | None = Field(default=None, nullable=True)
    likely_image_only: bool | None = Field(default=None, nullable=True)
