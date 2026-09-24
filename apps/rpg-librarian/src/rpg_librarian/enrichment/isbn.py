from __future__ import annotations

from ..model import IsbnResult, ProcessingStage
from ..model.core import FileMetadataBase
from . import isbn_lookup
from .base import FatalSourceError
from .queries import FileContext


class IsbnSource:
    """Bibliographic lookup for the ISBN `scan` found in the file.

    Tries Google Books (if `GOOGLE_BOOKS_API_KEY` is set), then Open Library, then
    Wikidata. Google Books being unusable stops the source: the other two providers'
    hit rate alone is too low to carry a run.
    """

    name = "isbn"
    stage = ProcessingStage.isbn
    table = IsbnResult

    def unavailable_reason(self) -> str | None:
        return None  # Open Library and Wikidata need no key

    def begin_run(self) -> None:
        pass

    def wants(self, context: FileContext) -> bool:
        return context.isbn is not None

    def fetch(self, context: FileContext) -> FileMetadataBase | None:
        assert context.isbn is not None
        try:
            found = isbn_lookup.lookup(context.isbn)
        except isbn_lookup.GoogleBooksUnavailableError as error:
            raise FatalSourceError(str(error)) from error
        results = []
        if found is not None:
            results.append(
                {
                    "provider": found.provider,
                    "title": found.title,
                    "authors": found.authors,
                    "publisher": found.publisher,
                    "year": found.year,
                    "description": found.description,
                }
            )
        return IsbnResult(query=context.isbn, results=results)
