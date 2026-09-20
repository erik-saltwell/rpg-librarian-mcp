from __future__ import annotations

from collections.abc import Awaitable, Callable

from rpg_librarian_tools.rpggeek import Candidate, search

from .ProductLookupResult import ProductCandidate


class SearchRpgGeekCommand:
    def __init__(
        self,
        bearer_token: str | None,
        search_operation: Callable[[str, int, str | None], Awaitable[list[Candidate]]]
        | None = None,
    ) -> None:
        self.bearer_token = bearer_token
        self.search_operation = search_operation

    async def run(
        self, name: str | None, isbn: str | None, max_values: int = 5
    ) -> list[ProductCandidate]:
        if max_values < 1:
            raise ValueError(f"max_values must be a positive integer, got {max_values}")
        if name is None and isbn is None:
            raise ValueError("At least one of name or isbn must be provided")

        candidates = []
        if isbn is not None:
            candidates = await self._search(isbn, max_values)
        if not candidates and name is not None:
            candidates = await self._search(name, max_values)
        return [
            ProductCandidate(
                source="rpggeek",
                source_id=str(c.rpggeek_id),
                title=c.name,
                year_published=c.year_published,
            )
            for c in candidates
        ]

    async def _search(self, query: str, limit: int) -> list[Candidate]:
        if self.search_operation is not None:
            return await self.search_operation(query, limit, self.bearer_token)
        return await search(query, limit, bearer_token=self.bearer_token)
