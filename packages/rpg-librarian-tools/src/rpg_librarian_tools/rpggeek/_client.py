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
from pydantic import BaseModel, ConfigDict

from ..errors import AuthenticationError, RateLimitError, RemoteServiceError
from ..request_policy import DEFAULT_REQUEST_POLICY, RequestPolicy

log = logging.getLogger(__name__)

_BASE_URL = "https://rpggeek.com/xmlapi2"
type QueryValue = str | int | float | None


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    rpggeek_id: int
    name: str
    year_published: int | None = None


class ProductDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    rpggeek_id: int
    name: str
    year_published: int | None = None
    description: str | None = None
    systems: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    designers: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    thumbnail_url: str | None = None
    rating: float | None = None


@dataclass
class _RpgGeekApi:
    policy: RequestPolicy = field(default=DEFAULT_REQUEST_POLICY)
    bearer_token: str | None = field(default=None, repr=False)
    _http: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        token = self.bearer_token or ""
        if not token:
            log.warning("RPGGEEK_BEARER_TOKEN not set; calling RPGGeek unauthenticated")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(
            headers=headers, timeout=self.policy.timeout_seconds
        )

    async def _get(self, path: str, **params: QueryValue) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.policy.max_attempts):
            if self.policy.minimum_request_interval:
                await asyncio.sleep(self.policy.minimum_request_interval)
            try:
                response = await self._http.get(path, params=params)
                if response.status_code in (401, 403):
                    raise AuthenticationError("RPGGeek rejected the bearer token")
                if response.status_code == 429:
                    raise RateLimitError("RPGGeek")
                if response.is_error:
                    raise RemoteServiceError(
                        "RPGGeek", response.status_code, response.status_code >= 500
                    )
                return response
            except RemoteServiceError as error:
                if not error.retryable:
                    raise
                last_error = error
                if attempt + 1 < self.policy.max_attempts:
                    await asyncio.sleep(self.policy.backoff_seconds * (2**attempt))
            except (httpx.HTTPError, RateLimitError) as error:
                last_error = error
                if attempt + 1 < self.policy.max_attempts:
                    await asyncio.sleep(self.policy.backoff_seconds * (2**attempt))
        if isinstance(last_error, (RateLimitError, RemoteServiceError)):
            raise last_error
        raise RemoteServiceError("RPGGeek", retryable=True) from last_error

    async def search(self, query: str, max_values: int = 5) -> list[Candidate]:
        """Search RPGGeek once using a single name, ISBN, or other query."""
        response = await self._get(
            f"{_BASE_URL}/search",
            query=query,
            type="rpgitem",
        )
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
        response = await self._get(
            f"{_BASE_URL}/thing",
            id=rpggeek_id,
            type="rpgitem",
            stats=1,
        )
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

    async def __aenter__(self) -> _RpgGeekApi:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()


async def search_rpggeek(
    query: str,
    max_values: int = 5,
    *,
    bearer_token: str | None = None,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> tuple[Candidate, ...]:
    """Perform one self-contained RPGGeek search operation."""
    async with _RpgGeekApi(bearer_token=bearer_token, policy=policy) as client:
        return tuple(await client.search(query, max_values))


async def get_rpggeek_product(
    rpggeek_id: int,
    *,
    bearer_token: str | None = None,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> ProductDetails:
    """Perform one self-contained RPGGeek product lookup operation."""
    async with _RpgGeekApi(bearer_token=bearer_token, policy=policy) as client:
        return await client.get_product_details(rpggeek_id)
