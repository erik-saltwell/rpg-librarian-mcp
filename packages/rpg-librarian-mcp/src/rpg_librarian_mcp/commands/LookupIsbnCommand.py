from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rpg_librarian_tools.identifiers import IdentifierKind, find_publication_identifiers

from ..isbn import lookup as isbn_lookup
from .ProductLookupResult import ProductLookupDetails


@dataclass
class LookupIsbnCommand:
    lookup_isbn: Callable[[str], isbn_lookup.IsbnLookupResult | None] = (
        isbn_lookup.lookup
    )

    def run(self, isbn: str) -> ProductLookupDetails | None:
        identifiers = find_publication_identifiers(isbn)
        result_identifier = next(
            (item for item in identifiers if item.kind is IdentifierKind.ISBN), None
        )
        if result_identifier is None:
            return None
        normalized = result_identifier.value

        try:
            result = self.lookup_isbn(normalized)
        except isbn_lookup.GoogleBooksUnavailableError as error:
            raise isbn_lookup.GoogleBooksUnavailableError(
                f"{error} -- Open Library/Wikidata fallback was not "
                "attempted: Google Books being unusable (quota/key/rate "
                "limit) is treated as a stop condition, not a per-ISBN "
                "miss, since the other two providers' hit rate alone is "
                "too low to rely on"
            ) from error
        if result is None:
            return None

        return ProductLookupDetails(
            source="isbn",
            source_id=normalized,
            title=result.title or "",
            creators=result.authors,
            publisher=result.publisher,
            year_published=int(result.year)
            if result.year and result.year.isdigit()
            else None,
            description=result.description,
        )
