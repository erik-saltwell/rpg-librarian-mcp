from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from rpg_librarian_tools.dtrpg import Product, search_library, search_products

from .ProductLookupResult import ProductLookupDetails


class SearchDtrpgCommand:
    def __init__(
        self,
        api_key: str,
        product_search: Callable[
            [str, str, int], Awaitable[tuple[Product, ...]]
        ] = search_products,
        library_search: Callable[
            [str, str, int], Awaitable[tuple[Product, ...]]
        ] = search_library,
    ) -> None:
        self.api_key = api_key
        self.product_search = product_search
        self.library_search = library_search

    async def run(
        self,
        query: str,
        scope: Literal["library", "catalog"] = "catalog",
        max_values: int = 10,
    ) -> list[ProductLookupDetails]:
        if max_values < 1:
            raise ValueError(f"max_values must be a positive integer, got {max_values}")

        results = await (
            self.library_search(query, self.api_key, max_values)
            if scope == "library"
            else self.product_search(query, self.api_key, max_values)
        )
        return [
            ProductLookupDetails(
                source="dtrpg",
                source_id=str(r.product_id),
                title=r.title,
                description=r.description or None,
                publisher=r.publisher or None,
                system=r.game_system,
                creators=r.authors,
            )
            for r in results
        ]
