from __future__ import annotations

from ..rpggeek import RpgGeekClient
from .ProductLookupResult import ProductCandidate


class SearchRpgGeekCommand:
    def __init__(self, client: RpgGeekClient) -> None:
        self.client = client

    async def run(
        self, name: str | None, isbn: str | None, max_values: int = 5
    ) -> list[ProductCandidate]:
        candidates = await self.client.find_candidates(name, isbn, max_values)
        return [
            ProductCandidate(
                source="rpggeek",
                source_id=str(c.rpggeek_id),
                title=c.name,
                year_published=c.year_published,
            )
            for c in candidates
        ]
