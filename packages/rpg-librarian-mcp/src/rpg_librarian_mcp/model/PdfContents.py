from __future__ import annotations

from sqlmodel import Field

from .core import EntryMetadataBase


class PdfContents(EntryMetadataBase, table=True):
    """Barcode/text/LLM-derived signal extracted from a PDF's pages, read_pdfs's output.

    `possible_system` is raw, per-source signal (this PDF's own LLM guess),
    not the curated answer -- it feeds a future curation step that
    reconciles hints into `Product.system`, it is never written there
    directly.
    """

    barcode: str | None = Field(default=None, nullable=True)
    isbn: str | None = Field(default=None, nullable=True)
    issn: str | None = Field(default=None, nullable=True)
    sample_text: str | None = Field(default=None, nullable=True)
    description: str | None = Field(default=None, nullable=True)
    possible_system: str | None = Field(default=None, nullable=True)
