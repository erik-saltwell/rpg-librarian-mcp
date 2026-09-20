from __future__ import annotations

import asyncio
import os

from rpg_librarian_tools.errors import AuthenticationError, RateLimitError
from rpg_librarian_tools.google import search
from rpg_librarian_tools.request_policy import RequestPolicy

from ..model import GoogleSearchResult, ProcessingStage
from ..model.core import FileMetadataBase
from .base import FatalSourceError
from .queries import FileContext, google_query

_ENV = "SERPER_API_KEY"
_HITS = 5
# Serper tolerates far more than the default one request per second.
_POLICY = RequestPolicy(minimum_request_interval=0.2)


class GoogleSource:
    """A simple Google search per file, fetched through Serper.dev."""

    name = "google"
    stage = ProcessingStage.google
    table = GoogleSearchResult

    def unavailable_reason(self) -> str | None:
        return None if os.environ.get(_ENV) else f"{_ENV} is not set"

    def wants(self, context: FileContext) -> bool:
        return True

    def fetch(self, context: FileContext) -> FileMetadataBase | None:
        query = google_query(context)
        try:
            hits = asyncio.run(search(query, os.environ[_ENV], _HITS, policy=_POLICY))
        except (AuthenticationError, RateLimitError) as error:
            raise FatalSourceError(f"Serper: {error!r}") from error
        return GoogleSearchResult(
            query=query,
            results=[
                {
                    "position": hit.position,
                    "title": hit.title,
                    "url": hit.url,
                    "snippet": hit.snippet,
                }
                for hit in hits
            ],
        )
