"""Deterministic search queries for a file. No LLM is involved, and every query
is stored with its results so it can be inspected."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEPARATORS = re.compile(r"[_\-\s]+")
_PUNCTUATION = re.compile(r"[^\w\s]")
_MIN_QUERY_LENGTH = 3
MAX_ATTEMPTS = 4  # requests per file per source, at most


@dataclass(frozen=True, slots=True)
class FileContext:
    """What `enrich` knows about one file, loaded from the catalog."""

    file_id: int
    path: str  # absolute, for logging
    relative_path: str
    title: str | None = None
    isbn: str | None = None
    # None: the file has no `file_text` row (not a PDF, or unreadable).
    sample_pages: dict[str, str] | None = None


def _words(text: str) -> str:
    return _SEPARATORS.sub(" ", _CAMEL_BOUNDARY.sub(" ", text)).strip()


def name_query(context: FileContext) -> str:
    """The embedded title, else the filename stem with its parent folder name."""
    if context.title and context.title.strip():
        return context.title.strip()
    path = PurePosixPath(context.relative_path)
    parts = [_words(path.stem)]
    if path.parent.name:
        parts.append(_words(path.parent.name))
    return " ".join(part for part in parts if part)


def comparable_name(name: str) -> str:
    """A name reduced for equality checks: case, punctuation, and `&` versus `and`
    are ignored, so "Blood & Bone" and "Blood and Bone" compare equal."""
    folded = name.casefold().replace("&", " and ")
    return " ".join(_PUNCTUATION.sub(" ", folded).split())


def name_ladder(context: FileContext) -> list[str]:
    """Queries for a strict catalog search, simplest-to-most-general, without repeats.

    DriveThruRPG and RPGGeek match on *every* word, so a query padded with an author
    or a generic folder ("Core Rules") finds nothing where the bare product name
    finds it. So: the embedded title, then the filename stem, then each ancestor
    folder from the top down (a top-level folder is usually the product or line).
    """
    path = PurePosixPath(context.relative_path)
    candidates = [context.title or "", _words(path.stem)]
    candidates += [_words(folder) for folder in path.parent.parts]
    ladder: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if len(candidate) >= _MIN_QUERY_LENGTH and candidate not in ladder:
            ladder.append(candidate)
    return ladder


def try_queries[T](
    queries: list[str], attempt: Callable[[str], Sequence[T]]
) -> tuple[str, Sequence[T]]:
    """Run queries in order until one has results; return (query used, results).

    Stops after `MAX_ATTEMPTS`. With no hits, returns the last query tried and an
    empty result, so the caller can record what was searched.
    """
    used, found = queries[0], ()
    for query in queries[:MAX_ATTEMPTS]:
        used, found = query, attempt(query)
        if found:
            break
    return used, found


def google_query(context: FileContext) -> str:
    """An identified ISBN, else the name query."""
    return context.isbn or name_query(context)
