"""Name matching for product types, lines, and products.

Names are stored as given (whitespace collapsed), and compared case-insensitively
with whitespace normalized, so "D&D  5e" and "d&d 5e" are the same name.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

_WHITESPACE = re.compile(r"\s+")
_SUGGESTION_CUTOFF = 0.6
NEAR_MATCH_CUTOFF = 0.85


def clean_name(name: str) -> str:
    """The stored form: surrounding whitespace dropped, inner runs collapsed."""
    return _WHITESPACE.sub(" ", name).strip()


def normalize_name(name: str) -> str:
    """The comparison form: `clean_name`, case-folded."""
    return clean_name(name).casefold()


def closest_names(
    name: str,
    candidates: Iterable[str],
    *,
    limit: int = 3,
    cutoff: float = _SUGGESTION_CUTOFF,
) -> list[str]:
    """Up to `limit` candidates most similar to `name`, best first."""
    by_key = {normalize_name(candidate): candidate for candidate in candidates}
    matches = difflib.get_close_matches(
        normalize_name(name), by_key, n=limit, cutoff=cutoff
    )
    return [by_key[key] for key in matches]


def near_matches(name: str, candidates: Iterable[str]) -> list[str]:
    """Candidates that look like a typo of `name` but are not the same name."""
    key = normalize_name(name)
    return [
        candidate
        for candidate in closest_names(name, candidates, cutoff=NEAR_MATCH_CUTOFF)
        if normalize_name(candidate) != key
    ]
