from __future__ import annotations

from enum import StrEnum


class PackFormation(StrEnum):
    """How a pack came to exist."""

    find_packs = "find-packs"  # proposed by the LLM, validated, formed losslessly
    create_pack = "create-pack"  # made by hand through the `create-pack` tool
