from __future__ import annotations

from enum import StrEnum


class Disposition(StrEnum):
    """A file's declared end state; `reorganize` renders it onto the share."""

    unfiled = "unfiled"
    keep = "keep"
    duplicate = "duplicate"
    superseded = "superseded"
    discard = "discard"
