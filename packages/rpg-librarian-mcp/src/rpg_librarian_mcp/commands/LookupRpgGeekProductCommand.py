from __future__ import annotations

from collections.abc import Awaitable, Callable

from rpg_librarian_tools.rpggeek import ProductDetails, get_product

from .ProductLookupResult import ProductLookupDetails


class LookupRpgGeekProductCommand:
    def __init__(
        self,
        bearer_token: str | None,
        lookup_operation: Callable[[int, str | None], Awaitable[ProductDetails]]
        | None = None,
    ) -> None:
        self.bearer_token = bearer_token
        self.lookup_operation = lookup_operation

    async def run(self, rpggeek_id: int) -> ProductLookupDetails:
        if rpggeek_id <= 0:
            raise ValueError(f"rpggeek_id must be a positive integer, got {rpggeek_id}")

        details = await self._lookup(rpggeek_id)
        return ProductLookupDetails(
            source="rpggeek",
            source_id=str(details.rpggeek_id),
            title=details.name,
            year_published=details.year_published,
            description=details.description,
            publisher="; ".join(details.publishers) or None,
            system="; ".join(details.systems) or None,
            creators=details.designers,
            thumbnail_url=details.thumbnail_url,
            rating=details.rating,
            categories=details.categories,
        )

    async def _lookup(self, rpggeek_id: int) -> ProductDetails:
        if self.lookup_operation is not None:
            return await self.lookup_operation(rpggeek_id, self.bearer_token)
        return await get_product(rpggeek_id, bearer_token=self.bearer_token)
