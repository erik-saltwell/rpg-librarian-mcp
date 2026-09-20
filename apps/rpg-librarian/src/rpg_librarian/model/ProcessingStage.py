from __future__ import annotations

from enum import StrEnum


class ProcessingStage(StrEnum):
    """The verb or sub-step an `Error` row was raised in."""

    scan = "scan"
    metadata = "metadata"
    text = "text"
    dtrpg = "dtrpg"
    rpggeek = "rpggeek"
    isbn = "isbn"
    google = "google"
    llm = "llm"
    reorganize = "reorganize"
