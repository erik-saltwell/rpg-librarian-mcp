from __future__ import annotations

from enum import StrEnum


class EntryType(StrEnum):
    """Which kind of thing an `Entry` is, and so which of its foreign keys is set."""

    file = "file"
    pack = "pack"
