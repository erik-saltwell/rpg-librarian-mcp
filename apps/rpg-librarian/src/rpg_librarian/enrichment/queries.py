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
# A title ending in a file extension ("interior.indd") is a tool artifact, not a title.
_EXTENSION_SUFFIX = re.compile(r"\.[A-Za-z0-9]{2,5}$")
# DriveThruRPG downloads carry the order id in the filename: "Play_Dirty_(8113103)".
_STORE_ORDER_ID = re.compile(r"\s*\(\d{6,}\)")
_MIN_QUERY_LENGTH = 3
MAX_ATTEMPTS = 4  # requests per file per source, at most
# A pack is the first folders below the root: `<type>/<line>/<product>` in the library,
# `<game>/<pack>/<section>` in a dump. Deeper folders split one pack into many.
PACK_DEPTH = 3
_MAX_PACK_QUERY_WORDS = 16


@dataclass(frozen=True, slots=True)
class FileContext:
    """What `enrich` knows about one file, loaded from the catalog."""

    file_id: int
    path: str  # absolute, for logging
    relative_path: str
    title: str | None = None
    isbn: str | None = None
    media_type: str | None = None  # the `MediaType` value, e.g. "pdf"
    # None: the file has no `file_text` row (not a PDF, or unreadable).
    sample_pages: dict[str, str] | None = None


def _words(text: str) -> str:
    return _SEPARATORS.sub(" ", _CAMEL_BOUNDARY.sub(" ", text)).strip()


def _stem_words(relative_path: str) -> str:
    return _words(_STORE_ORDER_ID.sub("", PurePosixPath(relative_path).stem))


def _usable_title(title: str | None) -> str:
    cleaned = (title or "").strip()
    return "" if _EXTENSION_SUFFIX.search(cleaned) else cleaned


def is_product_document(context: FileContext) -> bool:
    """A file that can itself be a product's book or sheet: a PDF that is not an `.ai`.

    Audio, meshes, images, plain text, and `.ai` maps are pieces of a pack. Searching
    for one by its own name ("Battle 1", "Handle_Long") finds unrelated products, and
    the top-level folder of a pack is often a category ("system agnostic", "Maps"),
    not a product, so a strict catalog search cannot use it. Google looks such files
    up by their pack instead (`pack_query`).
    """
    return context.media_type == "pdf" and not context.relative_path.lower().endswith(
        ".ai"
    )


def top_level_folder(context: FileContext) -> str:
    parts = PurePosixPath(context.relative_path).parts
    return _words(parts[0]) if len(parts) > 1 else ""


def name_query(context: FileContext) -> str:
    """The embedded title, else the filename stem with its parent folder name."""
    title = _usable_title(context.title)
    if title:
        return title
    path = PurePosixPath(context.relative_path)
    stem = _stem_words(context.relative_path)
    parent = _words(path.parent.name) if path.parent.name else ""
    # Skip a parent folder that only repeats the filename (or the other way round).
    repeats = (
        parent.casefold() in stem.casefold() or stem.casefold() in parent.casefold()
    )
    return " ".join(part for part in (stem, "" if repeats else parent) if part)


def pack_query(context: FileContext) -> str:
    """The pack a non-document file belongs to, as one query shared by all its files.

    The words of the first `PACK_DEPTH` folders, without hidden folders (`.trash`),
    store order ids, or repeated words: "Heart The City Beneath/Heart The City Beneath -
    Map Set" becomes "Heart The City Beneath Map Set". Empty for a file with no folder.
    """
    folders = [
        folder
        for folder in PurePosixPath(context.relative_path).parent.parts
        if not folder.startswith(".")
    ][:PACK_DEPTH]
    words: list[str] = []
    seen: set[str] = set()
    for folder in folders:
        for word in _words(_STORE_ORDER_ID.sub("", folder)).split():
            if word.casefold() not in seen:
                seen.add(word.casefold())
                words.append(word)
    return " ".join(words[:_MAX_PACK_QUERY_WORDS])


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
    candidates = [_usable_title(context.title), _stem_words(context.relative_path)]
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
    """An identified ISBN, else the name query.

    For a product document the top-level folder (nearly always the product or line) is
    appended when the query does not already contain it: Google tolerates extra words,
    and it rescues generic or junk titles ("Series Worksheet", "Sheet1-1").
    """
    if context.isbn:
        return context.isbn
    query = name_query(context)
    folder = top_level_folder(context)
    if (
        is_product_document(context)
        and folder
        and folder.casefold() not in query.casefold()
    ):
        query = f"{query} {folder}"
    return query
