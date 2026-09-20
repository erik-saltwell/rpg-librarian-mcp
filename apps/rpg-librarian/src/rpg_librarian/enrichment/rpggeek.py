from __future__ import annotations

import asyncio
import os

from rpg_librarian_tools.errors import AuthenticationError, RateLimitError
from rpg_librarian_tools.rpggeek import get_product, search

from ..model import ProcessingStage, RpggeekResult
from ..model.core import FileMetadataBase
from ..observability import log_file_fields
from .base import FatalSourceError
from .queries import FileContext, name_ladder, try_queries

_ENV = "RPGGEEK_BEARER_TOKEN"
_CANDIDATES = 5
_MAX_DESCRIPTION = 1000


class RpggeekSource:
    """RPGGeek search: by ISBN when the file has one, then by name.

    The first candidate also carries its product details (publishers, designers,
    systems). Later candidates carry only id, name, and year, to keep the request
    count to a search plus one lookup per file.
    """

    name = "rpggeek"
    stage = ProcessingStage.rpggeek
    table = RpggeekResult

    def unavailable_reason(self) -> str | None:
        # RPGGeek now rejects unauthenticated calls, so the token is required.
        return None if os.environ.get(_ENV) else f"{_ENV} is not set"

    def wants(self, context: FileContext) -> bool:
        return True

    def fetch(self, context: FileContext) -> FileMetadataBase | None:
        token = os.environ.get(_ENV)
        queries = [q for q in (context.isbn, *name_ladder(context)) if q]
        if not queries:
            return None
        try:
            query, candidates = try_queries(
                queries,
                lambda q: asyncio.run(search(q, _CANDIDATES, bearer_token=token)),
            )
            results: list[dict] = [
                {
                    "rpggeek_id": c.rpggeek_id,
                    "name": c.name,
                    "year_published": c.year_published,
                }
                for c in candidates
            ]
            if candidates:
                try:
                    details = asyncio.run(
                        get_product(candidates[0].rpggeek_id, bearer_token=token)
                    )
                except ValueError:
                    pass  # the candidate vanished between search and lookup
                else:
                    results[0] |= {
                        "description": (details.description or "")[:_MAX_DESCRIPTION],
                        "systems": list(details.systems),
                        "categories": list(details.categories),
                        "designers": list(details.designers),
                        "publishers": list(details.publishers),
                    }
        except (AuthenticationError, RateLimitError) as error:
            raise FatalSourceError(f"RPGGeek: {error!r}") from error
        log_file_fields(rpggeek_query=query)
        return RpggeekResult(query=query, results=results)
