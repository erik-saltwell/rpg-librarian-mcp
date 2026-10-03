from __future__ import annotations

from enum import StrEnum


class FolderOutcome(StrEnum):
    """What `find-packs` concluded about one folder."""

    pack = "pack"  # the folder is a pack (and one was formed)
    container = "container"  # holds packs further down; see `details.children`
    no_packs = "no_packs"  # nothing below is a pack
    mixed = "mixed"  # a pack, but forming it would lose an existing decision
    invalid = "invalid"  # the answer failed validation (overlap, unknown path, ...)
    error = "error"  # the search or the LLM call failed; retried next run
