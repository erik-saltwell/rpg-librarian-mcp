from __future__ import annotations

from rpg_librarian_mcp.commands.LookupIsbnCommand import LookupIsbnCommand
from rpg_librarian_mcp.isbn.lookup import IsbnLookupResult

VALID_ISBN_13 = "978-0-306-40615-7"
VALID_ISBN_13_NORMALIZED = "9780306406157"
VALID_ISSN = "2049-3630"


def test_run_maps_found_result_to_product_lookup_details():
    calls: list[str] = []

    def fake_lookup(isbn: str) -> IsbnLookupResult | None:
        calls.append(isbn)
        return IsbnLookupResult(
            title="Call of Cthulhu 7E",
            authors=["Sandy Petersen", "Mike Mason"],
            publisher="Chaosium",
            year="2014",
            description="A game of horror.",
        )

    result = LookupIsbnCommand(lookup_isbn=fake_lookup).run(VALID_ISBN_13)

    assert calls == [VALID_ISBN_13_NORMALIZED]
    assert result is not None
    assert result.source == "isbn"
    assert result.source_id == VALID_ISBN_13_NORMALIZED
    assert result.title == "Call of Cthulhu 7E"
    assert result.creators == ["Sandy Petersen", "Mike Mason"]
    assert result.publisher == "Chaosium"
    assert result.year_published == 2014
    assert result.description == "A game of horror."


def test_run_returns_none_without_calling_lookup_for_invalid_isbn():
    def fail_if_called(isbn: str) -> IsbnLookupResult | None:
        raise AssertionError("should not query with an invalid ISBN")

    result = LookupIsbnCommand(lookup_isbn=fail_if_called).run("not-an-isbn")

    assert result is None


def test_run_returns_none_without_calling_lookup_for_an_issn():
    """ISSN input is not a valid ISBN, so it fails validation and never
    reaches the lookup callable -- lookup_isbn does not support periodicals."""

    def fail_if_called(isbn: str) -> IsbnLookupResult | None:
        raise AssertionError("should not query an ISSN against ISBN providers")

    result = LookupIsbnCommand(lookup_isbn=fail_if_called).run(VALID_ISSN)

    assert result is None


def test_run_returns_none_when_lookup_finds_no_match():
    result = LookupIsbnCommand(lookup_isbn=lambda isbn: None).run(VALID_ISBN_13)

    assert result is None


def test_run_handles_missing_year():
    result = LookupIsbnCommand(
        lookup_isbn=lambda isbn: IsbnLookupResult(
            title="Unlisted Game", authors=[], publisher=None, year=None
        )
    ).run(VALID_ISBN_13)

    assert result is not None
    assert result.year_published is None
