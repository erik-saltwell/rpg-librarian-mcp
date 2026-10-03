from __future__ import annotations

import asyncio
import os
from typing import Any

from rpg_librarian_tools.errors import AuthenticationError, RateLimitError
from rpg_librarian_tools.google import search
from rpg_librarian_tools.request_policy import RequestPolicy

from ..model import GoogleSearchResult, ProcessingStage
from .base import FatalSourceError
from .queries import (
    FileContext,
    google_query,
    is_product_document,
    pack_google_query,
    pack_query,
)

_ENV = "SERPER_API_KEY"
_HITS = 5
# Serper tolerates far more than the default one request per second.
_POLICY = RequestPolicy(minimum_request_interval=0.2)


class GoogleSource:
    """A simple Google search, fetched through Serper.dev.

    A product document is searched for on its own. Any other file (a token, a map, a
    track) is searched for by its pack (`pack_query`): every file of a pack shares one
    request and stores the same query and hits, so a 2,000-token pack costs one request,
    not 2,000 searches for names no one has indexed.
    """

    name = "google"
    stage = ProcessingStage.google
    table = GoogleSearchResult

    def __init__(self) -> None:
        # This run's outcome per query: its hits, or the error it failed with, so the
        # rest of a pack neither re-asks nor retries a failed query file by file.
        self._outcomes: dict[str, list[dict[str, Any]] | Exception] = {}

    def unavailable_reason(self) -> str | None:
        return None if os.environ.get(_ENV) else f"{_ENV} is not set"

    def begin_run(self) -> None:
        self._outcomes.clear()

    def wants(self, context: FileContext) -> bool:
        if context.pack is not None:  # usually covered already by find-packs
            return bool(pack_google_query(context.pack))
        return is_product_document(context) or bool(pack_query(context))

    def fetch(self, context: FileContext) -> GoogleSearchResult | None:
        if context.pack is not None:
            query = pack_google_query(context.pack)
        elif is_product_document(context):
            query = google_query(context)
        else:
            query = pack_query(context)
        if query not in self._outcomes:
            try:
                self._outcomes[query] = self._search(query)
            except FatalSourceError:
                raise
            except Exception as error:
                self._outcomes[query] = error
        outcome = self._outcomes[query]
        if isinstance(outcome, Exception):
            # A fresh error per file: re-raising the stored one grows its traceback.
            raise RuntimeError(f"Serper: {outcome!r}") from outcome
        return GoogleSearchResult(query=query, results=list(outcome))

    def _search(self, query: str) -> list[dict[str, Any]]:
        return serper_search(query)


def serper_available() -> str | None:
    """Why a Google search cannot run (no key), else None."""
    return None if os.environ.get(_ENV) else f"{_ENV} is not set"


def serper_search(query: str) -> list[dict[str, Any]]:
    """One Google search through Serper: the top hits as plain dicts.

    Raises `FatalSourceError` when the key is refused or the quota is exhausted, so the
    caller stops searching instead of failing every remaining query.
    """
    try:
        hits = asyncio.run(search(query, os.environ[_ENV], _HITS, policy=_POLICY))
    except (AuthenticationError, RateLimitError) as error:
        raise FatalSourceError(f"Serper: {error!r}") from error
    return [
        {
            "position": hit.position,
            "title": hit.title,
            "url": hit.url,
            "snippet": hit.snippet,
        }
        for hit in hits
    ]
