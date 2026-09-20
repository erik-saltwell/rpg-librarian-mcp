from __future__ import annotations

from sqlmodel import Field

from .core import FileMetadataBase


class FileLlmExtraction(FileMetadataBase, table=True):
    """LLM-derived signal for one file, written by `enrich`.

    Raw per-file signal, never a curated answer. "Needs enrichment" is the absence
    of this row for a file that has a `file_text` row.
    """

    __tablename__ = "file_llm_extraction"

    description: str | None = Field(default=None, nullable=True)
    possible_system: str | None = Field(default=None, nullable=True)
