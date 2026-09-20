from __future__ import annotations

from sqlalchemy import JSON, Column
from sqlmodel import Field

from .core import FileMetadataBase


class FileText(FileMetadataBase, table=True):
    """Barcode, identifiers, and a bounded page sample read from a PDF by `scan`.

    `sample_pages` is a JSON object keyed by page number. The sample is bounded
    (text: first 5 pages plus last 2; barcode: first 2 plus last 1), never full text.
    """

    __tablename__ = "file_text"

    barcode: str | None = Field(default=None, nullable=True)
    isbn: str | None = Field(default=None, nullable=True, index=True)
    issn: str | None = Field(default=None, nullable=True, index=True)
    sample_pages: dict[str, str] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
