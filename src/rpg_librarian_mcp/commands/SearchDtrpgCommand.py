from __future__ import annotations

from typing import Literal

from ..dtrpg import DriveThruRPGClient
from .ProductLookupResult import ProductLookupDetails


class SearchDtrpgCommand:
    def __init__(self, client: DriveThruRPGClient) -> None:
        self.client = client

    def run(
        self,
        query: str,
        scope: Literal["library", "catalog"] = "catalog",
        max_values: int = 10,
    ) -> list[ProductLookupDetails]:
        results = (
            self.client.search_library(query, max_values)
            if scope == "library"
            else self.client.search_products(query, max_values)
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
