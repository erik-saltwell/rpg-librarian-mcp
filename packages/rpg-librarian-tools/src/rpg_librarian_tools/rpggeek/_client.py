"""Client for the RPGGeek (rpggeek.com) XML API.

Vendored from the sibling `rpggeek-mcp` project. Only functional change
from upstream: `structlog` calls converted to stdlib `logging`, matching
this project's convention -- XML parsing, the rate-limit sleep, and the
`/search` + `/thing` endpoint logic are otherwise unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel

from ..request_policy import DEFAULT_REQUEST_POLICY, RequestPolicy

log = logging.getLogger(__name__)

_BASE_URL = "https://rpggeek.com/xmlapi2"


class Candidate(BaseModel):
    rpggeek_id: int
    name: str
    year_published: int | None = None


class ProductDetails(BaseModel):
    rpggeek_id: int
    name: str
    year_published: int | None = None
    description: str | None = None
    systems: list[str] = []
    categories: list[str] = []
    designers: list[str] = []
    publishers: list[str] = []
    thumbnail_url: str | None = None
    rating: float | None = None


@dataclass
class RpgGeekClient:
    rate_limit_delay: float = field(default=1.0)
    bearer_token: str | None = field(default=None, repr=False)
    _http: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        token = self.bearer_token or ""
        if not token:
            log.warning("RPGGEEK_BEARER_TOKEN not set; calling RPGGeek unauthenticated")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(headers=headers)

    async def search(self, query: str, max_values: int = 5) -> list[Candidate]:
        """Search RPGGeek once using a single name, ISBN, or other query."""
        await asyncio.sleep(self.rate_limit_delay)
        response = await self._http.get(
            f"{_BASE_URL}/search",
            params={"query": query, "type": "rpgitem"},
        )
        response.raise_for_status()

        root = ET.fromstring(response.text)
        candidates = []
        for item in root.findall("item"):
            name_el = item.find("name")
            year_el = item.find("yearpublished")
            candidates.append(
                Candidate(
                    rpggeek_id=int(item.get("id", "0")),
                    name=name_el.get("value", "") if name_el is not None else "",
                    year_published=int(year_el.get("value", "0"))
                    if year_el is not None
                    else None,
                )
            )
        return candidates[:max_values]

    async def get_product_details(self, rpggeek_id: int) -> ProductDetails:
        await asyncio.sleep(self.rate_limit_delay)
        response = await self._http.get(
            f"{_BASE_URL}/thing",
            params={"id": rpggeek_id, "type": "rpgitem", "stats": 1},
        )
        response.raise_for_status()

        root = ET.fromstring(response.text)
        item = root.find("item")
        if item is None:
            raise ValueError(f"No RPGGeek item found for id {rpggeek_id}")

        name_el = item.find("name[@type='primary']")
        name = name_el.get("value", "") if name_el is not None else ""

        year_el = item.find("yearpublished")
        year_published = int(year_el.get("value", "0")) if year_el is not None else None

        desc_el = item.find("description")
        description = desc_el.text if desc_el is not None else None

        thumb_el = item.find("thumbnail")
        thumbnail_url = thumb_el.text if thumb_el is not None else None

        systems = [
            el.get("value", "").removeprefix("RPG System: ")
            for el in item.findall("link[@type='rpgfamily']")
            if el.get("value", "").startswith("RPG System:")
        ]
        categories = [
            el.get("value", "") for el in item.findall("link[@type='rpgcategory']")
        ]
        designers = [
            el.get("value", "") for el in item.findall("link[@type='rpgdesigner']")
        ]
        publishers = [
            el.get("value", "") for el in item.findall("link[@type='rpgpublisher']")
        ]

        rating_el = item.find("statistics/ratings/average")
        rating = float(rating_el.get("value", "0")) if rating_el is not None else None

        return ProductDetails(
            rpggeek_id=int(item.get("id", "0")),
            name=name,
            year_published=year_published,
            description=description,
            thumbnail_url=thumbnail_url,
            systems=systems,
            categories=categories,
            designers=designers,
            publishers=publishers,
            rating=rating,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RpgGeekClient:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()


async def search_rpggeek(
    query: str,
    max_values: int = 5,
    *,
    bearer_token: str | None = None,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> list[Candidate]:
    """Perform one self-contained RPGGeek search operation."""
    async with RpgGeekClient(
        rate_limit_delay=policy.minimum_request_interval, bearer_token=bearer_token
    ) as client:
        return await client.search(query, max_values)


async def get_rpggeek_product(
    rpggeek_id: int,
    *,
    bearer_token: str | None = None,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> ProductDetails:
    """Perform one self-contained RPGGeek product lookup operation."""
    async with RpgGeekClient(
        rate_limit_delay=policy.minimum_request_interval, bearer_token=bearer_token
    ) as client:
        return await client.get_product_details(rpggeek_id)
