from __future__ import annotations

import isbnlib
import pytest

from rpg_librarian_mcp.isbn import lookup as isbn_lookup
from rpg_librarian_mcp.observability import CallTracker

VALID_ISBN = "9780306406157"


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real 2s inter-call delay in tests -- it exists to protect
    live services, not to slow down a suite exercising fakes."""
    monkeypatch.setattr(isbn_lookup, "_throttle", lambda: None)


@pytest.fixture(autouse=True)
def _no_incidental_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep GOOGLE_BOOKS_API_KEY unset (so the keyed Google Books provider
    isn't exercised by tests that don't ask for it) and make any
    unexpectedly-real HTTP request fail loudly rather than hit the network.
    _open_library_description() swallows that failure and returns None, so
    plain meta()-only tests don't need to fake the Open Library follow-up
    request too; tests that care about it override _webquery themselves."""
    monkeypatch.delenv("GOOGLE_BOOKS_API_KEY", raising=False)

    def _unexpected_call(url: str) -> dict:
        raise RuntimeError(f"unexpected network call to {url}")

    monkeypatch.setattr(isbn_lookup, "_webquery", _unexpected_call)
    monkeypatch.setattr(isbn_lookup, "_fetch_google_books", _unexpected_call)


OPENL_META = {
    "Title": "From OpenL",
    "Authors": ["OpenL Author"],
    "Publisher": "OpenL Pub",
    "Year": "2002",
}
WIKI_META = {
    "Title": "From Wiki",
    "Authors": ["Wiki Author"],
    "Publisher": "Wiki Pub",
    "Year": "2003",
}
GOOGLE_ITEMS = {
    "items": [
        {
            "volumeInfo": {
                "title": "From Google",
                "authors": ["Google Author"],
                "publisher": "Google Pub",
                "publishedDate": "2004-05-01",
                "description": "A cracking good book.",
            }
        }
    ]
}


def test_isbnlib_meta_does_not_raise_module_not_found_for_pkg_resources() -> None:
    """Bug: isbnlib.registry does `from pkg_resources import iter_entry_points`
    at import time, and this environment has no `setuptools` (which provides
    `pkg_resources`) installed as a dependency, so every real lookup call
    raised ModuleNotFoundError instead of querying/returning None."""
    try:
        isbnlib.meta(VALID_ISBN, service="goob")
    except ModuleNotFoundError as exc:
        pytest.fail(f"isbnlib.meta raised {exc!r} -- missing dependency")
    except Exception:
        pass


def test_lookup_returns_openl_result_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_meta(isbn: str, service: str = "openl") -> dict:
        return OPENL_META if service == "openl" else {}

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From OpenL"


def test_lookup_falls_back_to_wiki_when_openl_has_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_meta(isbn: str, service: str = "openl") -> dict:
        return WIKI_META if service == "wiki" else {}

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From Wiki"


def test_lookup_falls_back_when_a_service_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_meta(isbn: str, service: str = "openl") -> dict:
        if service == "openl":
            raise RuntimeError("network error")
        return WIKI_META if service == "wiki" else {}

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From Wiki"


def test_lookup_returns_none_when_no_service_has_a_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isbnlib, "meta", lambda isbn, service="openl": {})

    assert isbn_lookup.lookup(VALID_ISBN) is None


def test_lookup_reports_per_provider_call_counts_and_which_one_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_meta(isbn: str, service: str = "openl") -> dict:
        return WIKI_META if service == "wiki" else {}

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    with CallTracker("lookup_isbn", transport="cli") as tracker:
        isbn_lookup.lookup(VALID_ISBN)

    assert tracker.event_fields["open_library_calls"] == 1
    assert tracker.event_fields["wikidata_calls"] == 1
    assert tracker.event_fields["google_books_calls"] == 0
    assert tracker.event_fields["isbn_found_via"] == "wiki"


def test_lookup_reports_isbn_found_via_none_on_a_total_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isbnlib, "meta", lambda isbn, service="openl": {})

    with CallTracker("lookup_isbn", transport="cli") as tracker:
        isbn_lookup.lookup(VALID_ISBN)

    assert tracker.event_fields["isbn_found_via"] is None


def test_lookup_falls_through_cleanly_on_data_not_found_at_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from isbnlib.dev import DataNotFoundAtServiceError

    def fake_meta(isbn: str, service: str = "openl") -> dict:
        if service == "openl":
            raise DataNotFoundAtServiceError(isbn)
        return WIKI_META if service == "wiki" else {}

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From Wiki"


def test_lookup_raises_when_every_service_fails_for_a_real_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_meta(isbn: str, service: str = "openl") -> dict:
        raise RuntimeError(f"{service} is throttling requests")

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    with pytest.raises(RuntimeError, match="wiki is throttling requests"):
        isbn_lookup.lookup(VALID_ISBN)


def test_throttle_sleeps_to_enforce_the_minimum_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()  # restore the real _throttle for this test

    times = iter([100.5, 102.0])
    monkeypatch.setattr(isbn_lookup.time, "monotonic", lambda: next(times))
    sleeps: list[float] = []
    monkeypatch.setattr(isbn_lookup.time, "sleep", sleeps.append)
    monkeypatch.setattr(isbn_lookup, "_last_call_time", 100.0)

    isbn_lookup._throttle()

    assert sleeps == [pytest.approx(1.5)]


def test_throttle_does_not_sleep_when_interval_already_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()  # restore the real _throttle for this test

    monkeypatch.setattr(isbn_lookup.time, "monotonic", lambda: 105.0)
    sleeps: list[float] = []
    monkeypatch.setattr(isbn_lookup.time, "sleep", sleeps.append)
    monkeypatch.setattr(isbn_lookup, "_last_call_time", 100.0)

    isbn_lookup._throttle()

    assert sleeps == []


def test_lookup_returns_none_immediately_for_an_invalid_isbn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    def fake_meta(isbn: str, service: str = "openl") -> dict:
        nonlocal call_count
        call_count += 1
        raise isbnlib.NotValidISBNError(isbn)

    monkeypatch.setattr(isbnlib, "meta", fake_meta)

    assert isbn_lookup.lookup("not-an-isbn") is None
    assert call_count == 1


def _fail(*args: object, **kwargs: object) -> dict:
    raise AssertionError("should not fall back to isbnlib services")


def test_lookup_prefers_google_books_when_api_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")
    monkeypatch.setattr(isbn_lookup, "_fetch_google_books", lambda url: GOOGLE_ITEMS)
    monkeypatch.setattr(isbnlib, "meta", _fail)

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From Google"
    assert result.authors == ["Google Author"]
    assert result.publisher == "Google Pub"
    assert result.year == "2004"
    assert result.description == "A cracking good book."


def test_lookup_skips_google_books_when_api_key_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GOOGLE_BOOKS_API_KEY is unset by the autouse fixture, and _webquery is
    # stubbed there to fail loudly, so if Google Books were queried anyway
    # this would blow up instead of silently falling back.
    monkeypatch.setattr(
        isbnlib,
        "meta",
        lambda isbn, service="openl": OPENL_META if service == "openl" else {},
    )

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From OpenL"


def test_lookup_falls_back_past_google_books_when_it_has_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")
    monkeypatch.setattr(isbn_lookup, "_fetch_google_books", lambda url: {"items": []})
    monkeypatch.setattr(
        isbnlib,
        "meta",
        lambda isbn, service="openl": OPENL_META if service == "openl" else {},
    )

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From OpenL"


def test_lookup_falls_back_past_google_books_when_it_raises_a_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-quota failure (e.g. a network blip) is treated like any other
    provider failure: fall back and keep going."""
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")

    def failing_fetch(url: str) -> dict:
        raise RuntimeError("network error")

    monkeypatch.setattr(isbn_lookup, "_fetch_google_books", failing_fetch)
    monkeypatch.setattr(
        isbnlib,
        "meta",
        lambda isbn, service="openl": OPENL_META if service == "openl" else {},
    )

    result = isbn_lookup.lookup(VALID_ISBN)

    assert result is not None
    assert result.title == "From OpenL"


def test_lookup_propagates_google_books_unavailable_without_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quota exhausted/blocked/rate limited is different: Open Library and
    Wikidata's hit rate alone is too low to be worth grinding through, so
    the whole lookup should abort instead of falling back."""
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")

    def unavailable_fetch(url: str) -> dict:
        raise isbn_lookup.GoogleBooksUnavailableError(
            "Google Books returned 429: Too Many Requests"
        )

    monkeypatch.setattr(isbn_lookup, "_fetch_google_books", unavailable_fetch)
    monkeypatch.setattr(isbnlib, "meta", _fail)

    with pytest.raises(isbn_lookup.GoogleBooksUnavailableError):
        isbn_lookup.lookup(VALID_ISBN)


def test_lookup_returns_none_immediately_for_an_invalid_isbn_via_google_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")

    def fail_fetch(url: str) -> dict:
        raise AssertionError("should not query with an invalid ISBN")

    monkeypatch.setattr(isbn_lookup, "_fetch_google_books", fail_fetch)
    monkeypatch.setattr(isbnlib, "meta", _fail)

    assert isbn_lookup.lookup("not-an-isbn") is None


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_fetch_google_books_raises_unavailable_error_for_quota_and_block_codes(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    import urllib.error
    from email.message import Message

    monkeypatch.undo()  # exercise the real _fetch_google_books, not the autouse stub

    def fake_urlopen(request: object, timeout: float) -> None:
        raise urllib.error.HTTPError(
            "http://example.com", status_code, "blocked", Message(), None
        )

    monkeypatch.setattr(isbn_lookup.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(isbn_lookup.GoogleBooksUnavailableError):
        isbn_lookup._fetch_google_books("http://example.com")


def test_fetch_google_books_reraises_other_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error
    from email.message import Message

    monkeypatch.undo()  # exercise the real _fetch_google_books, not the autouse stub

    def fake_urlopen(request: object, timeout: float) -> None:
        raise urllib.error.HTTPError(
            "http://example.com", 500, "server error", Message(), None
        )

    monkeypatch.setattr(isbn_lookup.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError):
        isbn_lookup._fetch_google_books("http://example.com")


def test_open_library_description_follows_edition_to_work_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_webquery(url: str) -> dict:
        urls.append(url)
        if url.endswith("/isbn/9780306406157.json"):
            return {"works": [{"key": "/works/OL12345W"}]}
        return {"description": {"value": "A work-level description."}}

    monkeypatch.setattr(isbn_lookup, "_webquery", fake_webquery)

    description = isbn_lookup._open_library_description(VALID_ISBN)

    assert description == "A work-level description."
    assert urls == [
        "https://openlibrary.org/isbn/9780306406157.json",
        "https://openlibrary.org/works/OL12345W.json",
    ]


def test_open_library_description_handles_plain_string_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_webquery(url: str) -> dict:
        if "/isbn/" in url:
            return {"works": [{"key": "/works/OL12345W"}]}
        return {"description": "A plain-string description."}

    monkeypatch.setattr(isbn_lookup, "_webquery", fake_webquery)

    assert (
        isbn_lookup._open_library_description(VALID_ISBN)
        == "A plain-string description."
    )


def test_open_library_description_returns_none_when_edition_has_no_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isbn_lookup, "_webquery", lambda url: {"works": []})

    assert isbn_lookup._open_library_description(VALID_ISBN) is None


def test_open_library_description_returns_none_when_a_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_webquery(url: str) -> dict:
        raise RuntimeError("network error")

    monkeypatch.setattr(isbn_lookup, "_webquery", failing_webquery)

    assert isbn_lookup._open_library_description(VALID_ISBN) is None


def test_query_attaches_open_library_description_only_for_the_openl_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isbnlib, "meta", lambda isbn, service="openl": OPENL_META)
    monkeypatch.setattr(
        isbn_lookup, "_open_library_description", lambda isbn: "A cracking good book."
    )

    openl_result = isbn_lookup._query(VALID_ISBN, "openl")
    wiki_result = isbn_lookup._query(VALID_ISBN, "wiki")

    assert openl_result is not None
    assert openl_result.description == "A cracking good book."
    assert wiki_result is not None
    assert wiki_result.description is None
