from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from ..errors import AuthenticationError, RateLimitError, RemoteServiceError
from ..request_policy import DEFAULT_REQUEST_POLICY, RequestPolicy

_BASE_URL = "https://api.drivethrurpg.com/api/vBeta/"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "rpg-librarian-tools",
}
_LIBRARY_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class Product:
    product_id: int
    order_product_id: int | None
    title: str
    description: str
    publisher: str
    authors: tuple[str, ...] = field(default_factory=tuple)
    game_system: str | None = None


class _Api:
    def __init__(self, api_key: str, policy: RequestPolicy) -> None:
        self.api_key, self.policy = api_key, policy
        self.client = httpx.AsyncClient(
            base_url=_BASE_URL, headers=_HEADERS, timeout=policy.timeout_seconds
        )
        self.last_request = 0.0

    async def __aenter__(self) -> _Api:
        await self.authenticate()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.client.aclose()

    async def request(self, method: str, path: str, **params: object) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.policy.max_attempts):
            elapsed = asyncio.get_running_loop().time() - self.last_request
            if elapsed < self.policy.minimum_request_interval:
                await asyncio.sleep(self.policy.minimum_request_interval - elapsed)
            try:
                response = await self.client.request(method, path, params=params)
                self.last_request = asyncio.get_running_loop().time()
            except httpx.HTTPError as error:
                last_error, response = error, None
            if (
                response is not None
                and response.status_code != 429
                and response.status_code < 500
            ):
                return response
            last_error = RemoteServiceError(
                "DriveThruRPG", response.status_code if response else None, True
            )
            if attempt + 1 < self.policy.max_attempts:
                await asyncio.sleep(self.policy.backoff_seconds * (2**attempt))
        if isinstance(last_error, RemoteServiceError) and last_error.status_code == 429:
            raise RateLimitError("DriveThruRPG") from last_error
        raise RemoteServiceError("DriveThruRPG", retryable=True) from last_error

    async def authenticate(self) -> None:
        response = await self.request("POST", "auth_key", applicationKey=self.api_key)
        if response.status_code in (401, 403):
            raise AuthenticationError("DriveThruRPG rejected the API key")
        if response.is_error:
            raise RemoteServiceError("DriveThruRPG", response.status_code)
        try:
            self.client.headers["Authorization"] = response.json()["token"]
        except (KeyError, TypeError, ValueError) as error:
            raise AuthenticationError(
                "DriveThruRPG authentication returned no token"
            ) from error

    async def get(self, path: str, **params: object) -> list[dict]:
        response = await self.request("GET", path, **params)
        if response.status_code == 401:
            await self.authenticate()
            response = await self.request("GET", path, **params)
        if response.status_code in (401, 403):
            raise AuthenticationError("DriveThruRPG rejected the credentials")
        if response.is_error:
            raise RemoteServiceError("DriveThruRPG", response.status_code)
        data = response.json()
        if not isinstance(data, list):
            raise RemoteServiceError("DriveThruRPG")
        return data


def _game_system(filters: list[dict] | None) -> str | None:
    return next(
        (
            item["name"]
            for item in filters or []
            if item.get("parentName") == "Game System"
        ),
        None,
    )


def _library_product(item: dict) -> Product:
    description = item.get("product", {}).get("description", {})
    return Product(
        item["productId"],
        item["orderProductId"],
        item["name"],
        description.get("shortDescription", ""),
        item["publisher"]["name"],
        game_system=_game_system(item.get("filters")),
    )


def _catalog_product(item: dict) -> Product:
    description = item["description"]
    return Product(
        item["productId"],
        None,
        description["name"],
        description.get("shortDescription", ""),
        item["publisher"]["name"],
        tuple(item.get("authors", [])),
        _game_system(item.get("storefrontPrimaryFilterValues")),
    )


async def search_products(
    query: str,
    api_key: str,
    limit: int = 10,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> tuple[Product, ...]:
    """Search the public DriveThruRPG product catalog."""
    async with _Api(api_key, policy) as api:
        items = await api.get(
            "products", name=query, page=1, pageSize=limit, siteId=10, status=1
        )
    return tuple(_catalog_product(item) for item in items[:limit])


async def search_library(
    query: str,
    api_key: str,
    limit: int = 10,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> tuple[Product, ...]:
    """Search the authenticated caller's DriveThruRPG library."""
    matches: list[Product] = []
    async with _Api(api_key, policy) as api:
        page = 1
        while len(matches) < limit:
            items = await api.get(
                "order_products",
                getChecksum=1,
                getFilters=1,
                page=page,
                pageSize=_LIBRARY_PAGE_SIZE,
                library=1,
                archived=0,
            )
            if not items:
                break
            matches.extend(
                _library_product(item)
                for item in items
                if query.lower() in item["name"].lower()
            )
            page += 1
    return tuple(matches[:limit])
