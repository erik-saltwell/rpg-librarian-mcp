from __future__ import annotations

from sqlmodel import Field

from .core import FileMetadataBase


class PdfMetadata(FileMetadataBase, table=True):
    """Type-specific metadata for files where media_type == pdf."""

    __tablename__ = "pdf_metadata"

    page_count: int | None = Field(default=None, nullable=True)
    is_encrypted: bool | None = Field(default=None, nullable=True)
    needs_password: bool | None = Field(default=None, nullable=True)
    has_extractable_text: bool | None = Field(default=None, nullable=True)
    likely_scanned: bool | None = Field(default=None, nullable=True)
    likely_image_only: bool | None = Field(default=None, nullable=True)
