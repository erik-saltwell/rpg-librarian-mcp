"""The seed list of product types.

A constant in code, not a migration: `init` inserts any that are missing, so adding a
type is a code change. The LLM may also create types at runtime through
`update_product`, which is why this is a seed and not a closed set.
"""

from __future__ import annotations

SEED_PRODUCT_TYPES: tuple[str, ...] = (
    "games",
    "maps",
    "animated-maps",
    "soundfx",
    "soundtracks",
    "handout-art",
    "miniatures",
    "terrain",
    "vtt packs",
    "system-agnostic-text",
)
