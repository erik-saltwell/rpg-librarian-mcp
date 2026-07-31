"""isbn -- look up bibliographic metadata for an ISBN."""

from __future__ import annotations

from fastmcp import FastMCP

from ..catalog import Catalog
from ..commands.LookupIsbnCommand import LookupIsbnCommand
from ..commands.ProductLookupResult import ProductLookupDetails


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="lookup_isbn")
    def lookup_isbn(isbn: str) -> ProductLookupDetails | None:
        """Look up bibliographic metadata for an ISBN (Google Books,
        falling back to Open Library, then Wikidata).

        Returns None if `isbn` is invalid or no provider has data for it --
        not an error. Does not support ISSN (periodical) lookups; an ISSN
        input reliably returns None.
        """
        return LookupIsbnCommand().run(isbn)
