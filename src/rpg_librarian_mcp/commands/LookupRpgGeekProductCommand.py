from __future__ import annotations

from ..rpggeek import RpgGeekClient
from .ProductLookupResult import ProductLookupDetails


class LookupRpgGeekProductCommand:
    def __init__(self, client: RpgGeekClient) -> None:
        self.client = client

    async def run(self, rpggeek_id: int) -> ProductLookupDetails:
        details = await self.client.get_product_details(rpggeek_id)
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
