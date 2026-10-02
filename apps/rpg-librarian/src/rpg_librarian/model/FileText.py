from __future__ import annotations

from sqlalchemy import JSON, Column
from sqlmodel import Field

from .core import FileMetadataBase


class FileText(FileMetadataBase, table=True):
    """Identifiers and bounded PDF or plain-text samples read by `scan`.

    `sample_pages` uses string page numbers: physical PDF pages (extracted text
    or OCR from the first 5 plus last 2), or one logical plain-text sample at "1"
    (at most 64 KiB of UTF-8 text). Plain-text reads are also capped at 64 KiB;
    a UTF-8 BOM is removed and undecodable bytes replaced with U+FFFD.
    Barcode sampling covers the first 2 PDF pages plus last 1. Identifiers are
    extracted only for PDFs, and remain unset for plain text.
    """

    __tablename__ = "file_text"

    barcode: str | None = Field(default=None, nullable=True)
    isbn: str | None = Field(default=None, nullable=True, index=True)
    issn: str | None = Field(default=None, nullable=True, index=True)
    sample_pages: dict[str, str] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
