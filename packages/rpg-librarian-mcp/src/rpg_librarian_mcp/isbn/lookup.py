"""Bibliographic metadata lookup by ISBN.

Vendored from `~/proj/rpg-librarian`'s `isbn/isbn_lookup.py`. Tries Google
Books (only if `GOOGLE_BOOKS_API_KEY` is set), then Open Library, then
Wikidata, returning the first provider with a match.

Callers are expected to validate/normalize the ISBN via `isbn.validate`/
`isbn._normalize` *before* calling `lookup()` -- this module no longer
does its own validation with `isbnlib.NotValidISBNError` for that purpose
(this project's own `isbn.py` validator is already established and
tested, used elsewhere by `read_pdfs`'s barcode step; having two ISBN
validators in one package would be redundant). `isbnlib.EAN13` is still
used inside `_google_books_query`, but only to convert a (pre-validated)
ISBN-10 into ISBN-13/EAN form for the query URL, not to validate it.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import isbnlib
from isbnlib.dev import DataNotFoundAtServiceError, ISBNLibHTTPError
from isbnlib.dev.webquery import query as _webquery

from ..observability import log_entry_fields, log_event_fields

# Tried in order until one returns a match: Google Books (only if
# GOOGLE_BOOKS_API_KEY is set -- see _providers()), then Open Library, then
# Wikipedia/Wikidata as a last resort.
_SERVICES = ("openl", "wiki")

# Raised by a service when it simply has no data for this ISBN -- not a real
# failure, just a reason to fall through to the next service.
_NO_DATA_ERROR = DataNotFoundAtServiceError

# isbnlib self-throttles to 1s between calls to the *same* host, which isn't
# enough to avoid Google Books' anonymous rate limit at catalog scale.
# Enforce our own, longer delay between every outbound call regardless of
# which service/host it targets.
_MIN_CALL_INTERVAL_SECONDS = 2.0
_last_call_time: float = 0.0

# isbnlib's own Google Books ("goob") service has no way to pass an API key,
# so it's stuck on Google's anonymous quota. We query Google Books directly
# instead, keyed, which gets a much higher quota and also returns a
# description in the same response (isbnlib.desc()/meta()'s "openl"/"wiki"
# services don't provide one at all).
_GOOGLE_BOOKS_URL = (
    "https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    "&fields=items/volumeInfo(title,subtitle,authors,publisher,publishedDate,description)"
    "&maxResults=1&key={api_key}"
)
_GOOGLE_BOOKS_USER_AGENT = "rpg-librarian-mcp (gzip)"

# Status codes meaning Google Books itself is currently unusable -- quota
# exhausted, key blocked, or rate limited -- as opposed to a per-ISBN "no
# data" response. Every subsequent call this run will fail the same way, so
# these are raised as GoogleBooksUnavailableError (see below) rather than
# folded into the normal per-ISBN fallback/retry handling.
_GOOGLE_BOOKS_UNAVAILABLE_STATUS_CODES = (401, 403, 429)


class GoogleBooksUnavailableError(Exception):
    """Google Books itself is unusable right now (daily quota exhausted, key
    blocked, or rate limited), not just missing data for one ISBN.

    Open Library and Wikidata's hit rate on their own is low enough that
    continuing the run without Google Books for the rest of the catalog
    isn't worth it, so lookup() lets this propagate immediately instead of
    falling back -- callers should stop rather than retrying entry by entry.
    """


def _throttle() -> None:
    global _last_call_time
    elapsed = time.monotonic() - _last_call_time
    if elapsed < _MIN_CALL_INTERVAL_SECONDS:
        time.sleep(_MIN_CALL_INTERVAL_SECONDS - elapsed)
    _last_call_time = time.monotonic()


def _is_not_found_http_error(error: Exception) -> bool:
    """A 404 from a service (seen from Wikidata for obscure/small-press
    ISBNs) is that service's way of saying "no data", not a real failure --
    unlike isbnlib's own DataNotFoundAtServiceError, it isn't recognized as
    such upstream, so we treat it the same way here."""
    return isinstance(error, ISBNLibHTTPError) and "404" in str(error)


@dataclass
class IsbnLookupResult:
    title: str | None
    authors: list[str]
    publisher: str | None
    year: str | None
    description: str | None = None


def _open_library_description(isbn: str) -> str | None:
    """Best-effort description from Open Library's *work* record.

    isbnlib's "openl" service (and the edition record it's built from) has
    no description field -- only the work an edition belongs to does -- so
    this is a second, separate request beyond the meta() lookup.
    """
    try:
        _throttle()
        edition = _webquery(f"https://openlibrary.org/isbn/{isbn}.json")
        work_key = edition.get("works", [{}])[0].get("key")
        if not work_key:
            return None
        _throttle()
        work = _webquery(f"https://openlibrary.org{work_key}.json")
    except Exception:
        return None
    description = work.get("description")
    if isinstance(description, dict):
        description = description.get("value")
    return description or None


def _query(isbn: str, service: str) -> IsbnLookupResult | None:
    _throttle()
    meta = isbnlib.meta(isbn, service=service)
    if not meta:
        return None

    result = IsbnLookupResult(
        title=meta.get("Title") or None,
        authors=list(meta.get("Authors") or []),
        publisher=meta.get("Publisher") or None,
        year=meta.get("Year") or None,
    )
    if not any((result.title, result.authors, result.publisher, result.year)):
        return None
    if service == "openl":
        result.description = _open_library_description(isbn)
    return result


def _fetch_google_books(url: str) -> dict:
    """Fetch from Google Books directly (bypassing isbnlib's HTTP wrapper,
    which collapses every 401/403/429 into the same generic message and
    discards the status code) so a quota/blocked/rate-limit response can be
    told apart from a transient network error."""
    request = urllib.request.Request(
        url, headers={"User-Agent": _GOOGLE_BOOKS_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in _GOOGLE_BOOKS_UNAVAILABLE_STATUS_CODES:
            raise GoogleBooksUnavailableError(
                f"Google Books returned {error.code}: {error.reason}"
            ) from error
        raise


def _google_books_query(isbn: str, api_key: str) -> IsbnLookupResult | None:
    ean = isbnlib.EAN13(isbn)
    if not ean:
        raise isbnlib.NotValidISBNError(isbn)

    _throttle()
    data = _fetch_google_books(_GOOGLE_BOOKS_URL.format(isbn=ean, api_key=api_key))
    try:
        info = data["items"][0]["volumeInfo"]
    except KeyError, IndexError, TypeError:
        return None

    title = info.get("title") or None
    subtitle = info.get("subtitle")
    if title and subtitle:
        title = f"{title} - {subtitle}"
    published_date = info.get("publishedDate") or ""

    result = IsbnLookupResult(
        title=title,
        authors=list(info.get("authors") or []),
        publisher=info.get("publisher") or None,
        year=published_date[:4] or None,
        description=info.get("description") or None,
    )
    if not any((result.title, result.authors, result.publisher, result.year)):
        return None
    return result


_PROVIDER_FIELD_NAMES = {
    "google_books": "google_books_calls",
    "openl": "open_library_calls",
    "wiki": "wikidata_calls",
}


def _providers() -> list[tuple[str, Callable[[str], IsbnLookupResult | None]]]:
    providers: list[tuple[str, Callable[[str], IsbnLookupResult | None]]] = []
    api_key = os.environ.get("GOOGLE_BOOKS_API_KEY")
    if api_key:
        providers.append(
            ("google_books", partial(_google_books_query, api_key=api_key))
        )
    providers.extend(
        (service, partial(_query, service=service)) for service in _SERVICES
    )
    return providers


def lookup(isbn: str) -> IsbnLookupResult | None:
    """Look up bibliographic metadata for an ISBN, falling back across
    providers until one returns a match.

    Returns None once every provider has genuinely found no data for the
    ISBN (or the ISBN itself is invalid) -- a real lookup miss, which should
    not stop cataloging. If every provider instead failed for a real reason
    (network/HTTP error, service down, ...), re-raises the last such error so
    the caller can tell a miss apart from a lookup that couldn't be
    attempted at all.

    If Google Books itself is unusable (quota exhausted, key blocked, rate
    limited), raises GoogleBooksUnavailableError immediately instead of
    falling back to Open Library/Wikidata -- their hit rate alone is low
    enough that the caller should stop rather than grinding through the
    rest of the catalog without Google Books.

    Reports per-provider call counts and which provider (if any) found a
    match via `log_event_fields`/`log_entry_fields` -- whichever of a
    command-level or entry-level wide event is currently in flight, or
    both, or neither (a no-op outside of a tracked call/entry).
    """
    call_counts = {field_name: 0 for field_name in _PROVIDER_FIELD_NAMES.values()}
    last_error: Exception | None = None
    found_via: str | None = None
    result: IsbnLookupResult | None = None

    for provider_name, provider in _providers():
        call_counts[_PROVIDER_FIELD_NAMES[provider_name]] += 1
        try:
            result = provider(isbn)
        except isbnlib.NotValidISBNError:
            result = None
            break
        except GoogleBooksUnavailableError:
            _report_lookup_stats(call_counts, found_via=None)
            raise
        except _NO_DATA_ERROR:
            result = None
            continue
        except Exception as error:
            result = None
            if _is_not_found_http_error(error):
                continue
            last_error = error
            continue
        if result is not None:
            found_via = provider_name
            break

    _report_lookup_stats(call_counts, found_via=found_via)

    if found_via is None and last_error is not None:
        raise last_error
    return result if found_via else None


def _report_lookup_stats(call_counts: dict[str, int], found_via: str | None) -> None:
    fields = {**call_counts, "isbn_found_via": found_via}
    log_event_fields(**fields)
    log_entry_fields(**fields)
