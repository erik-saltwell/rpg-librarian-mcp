from __future__ import annotations

from sqlmodel import Field

from .core import EntryMetadataBase


class FileTextAnalysis(EntryMetadataBase, table=True):
    """What a model read out of a file's sampled text: a description and a system guess.

    Raw signal about the catalog item, never a curated answer, and never a product,
    line, or type (the LLM session decides those). Keyed by entry; "needs analysis"
    is the absence of this row for an entry whose file has a `file_text` row.
    """

    __tablename__ = "file_text_analysis"

    description: str | None = Field(default=None, nullable=True)
    possible_system: str | None = Field(default=None, nullable=True)
