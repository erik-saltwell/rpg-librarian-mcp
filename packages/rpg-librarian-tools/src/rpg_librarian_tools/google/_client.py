from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from ..errors import AuthenticationError, RateLimitError, RemoteServiceError
from ..request_policy import DEFAULT_REQUEST_POLICY, RequestPolicy

_SERVICE = "Serper"
_URL = "https://google.serper.dev/search"
_MAX_RESULTS = 10


@dataclass(frozen=True, slots=True)
class SearchHit:
    position: int
    title: str
    url: str
    snippet: str


def _hits(payload: object, limit: int) -> tuple[SearchHit, ...]:
    if not isinstance(payload, dict):
        raise RemoteServiceError(_SERVICE)
    organic = payload.get("organic") or []
    if not isinstance(organic, list):
        raise RemoteServiceError(_SERVICE)
    hits = [
        SearchHit(
            position=index,
            title=str(item.get("title") or ""),
            url=str(item.get("link") or ""),
            snippet=str(item.get("snippet") or ""),
        )
        for index, item in enumerate(organic, start=1)
        if isinstance(item, dict)
    ]
    return tuple(hits[:limit])


def _out_of_credits(response: httpx.Response) -> bool:
    """Serper reports an exhausted balance as a client error, not a 429."""
    if response.status_code == 402:
        return True
    if response.status_code != 400:
        return False
    try:
        return "credit" in str(response.json()).lower()
    except ValueError:
        return "credit" in response.text.lower()


async def search(
    query: str,
    api_key: str,
    num: int = 5,
    *,
    policy: RequestPolicy = DEFAULT_REQUEST_POLICY,
) -> tuple[SearchHit, ...]:
    """Perform one Google search through Serper and return the top organic hits.

    Retries transport errors, 429s, and 5xx responses per `policy`. A rejected key
    raises `AuthenticationError`; an exhausted balance or persistent 429 raises
    `RateLimitError`, which callers should treat as a reason to stop the run.
    """
    if not query.strip():
        raise ValueError("query cannot be empty")
    if not 1 <= num <= _MAX_RESULTS:
        raise ValueError(f"num must be between 1 and {_MAX_RESULTS}")

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        headers=headers, timeout=policy.timeout_seconds
    ) as client:
        for attempt in range(policy.max_attempts):
            if policy.minimum_request_interval:
                await asyncio.sleep(policy.minimum_request_interval)
            try:
                response = await client.post(_URL, json={"q": query, "num": num})
            except httpx.HTTPError as error:
                last_error = error
            else:
                if response.status_code in (401, 403):
                    raise AuthenticationError("Serper rejected the API key")
                if _out_of_credits(response):
                    raise RateLimitError(_SERVICE)
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RemoteServiceError(
                        _SERVICE, response.status_code, True
                    )
                elif response.is_error:
                    raise RemoteServiceError(_SERVICE, response.status_code)
                else:
                    try:
                        return _hits(response.json(), num)
                    except ValueError as error:
                        raise RemoteServiceError(_SERVICE) from error
            if attempt + 1 < policy.max_attempts:
                await asyncio.sleep(policy.backoff_seconds * (2**attempt))

    if isinstance(last_error, RemoteServiceError) and last_error.status_code == 429:
        raise RateLimitError(_SERVICE) from last_error
    raise RemoteServiceError(_SERVICE, retryable=True) from last_error
