from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..isbn import lookup as isbn_lookup
from ..isbn.isbn import _normalize, validate
from .ProductLookupResult import ProductLookupDetails


@dataclass
class LookupIsbnCommand:
    lookup_isbn: Callable[[str], isbn_lookup.IsbnLookupResult | None] = (
        isbn_lookup.lookup
    )

    def run(self, isbn: str) -> ProductLookupDetails | None:
        if not validate(isbn):
            return None
        normalized = _normalize(isbn)

        result = self.lookup_isbn(normalized)
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
