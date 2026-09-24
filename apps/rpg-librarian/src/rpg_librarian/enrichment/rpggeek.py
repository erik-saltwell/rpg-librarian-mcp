from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

from rpg_librarian_tools.errors import AuthenticationError, RateLimitError
from rpg_librarian_tools.rpggeek import Candidate, get_product, search

from ..model import ProcessingStage, RpggeekResult
from ..model.core import FileMetadataBase
from ..observability import log_file_fields
from .base import FatalSourceError
from .queries import (
    FileContext,
    comparable_name,
    is_product_document,
    name_ladder,
    try_queries,
)

_ENV = "RPGGEEK_BEARER_TOKEN"
_CANDIDATES = 5
_MAX_DESCRIPTION = 1000
_DETAIL_LIMIT = 3  # product lookups per file, at most


class RpggeekSource:
    """RPGGeek search for product documents (PDFs): by ISBN, then by name.

    The first candidate always carries its product details (publishers, designers,
    systems), and so does any other candidate whose name equals the query, up to
    `_DETAIL_LIMIT`. Ranking often puts a different product first (a newer edition, a
    namesake), so an exact name match earns a lookup wherever it ranks. The rest carry
    only id, name, and year, which keeps most files to a search plus one lookup. The
    LLM session still sees every candidate and makes the call.
    """

    name = "rpggeek"
    stage = ProcessingStage.rpggeek
    table = RpggeekResult

    def unavailable_reason(self) -> str | None:
        # RPGGeek now rejects unauthenticated calls, so the token is required.
        return None if os.environ.get(_ENV) else f"{_ENV} is not set"

    def begin_run(self) -> None:
        pass

    def wants(self, context: FileContext) -> bool:
        return is_product_document(context)

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
            for index in _detail_targets(query, candidates):
                try:
                    details = asyncio.run(
                        get_product(candidates[index].rpggeek_id, bearer_token=token)
                    )
                except ValueError:
                    continue  # the candidate vanished between search and lookup
                results[index] |= {
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


def _detail_targets(query: str, candidates: Sequence[Candidate]) -> list[int]:
    """Indexes to look up in full: the first, then exact name matches, capped."""
    if not candidates:
        return []
    wanted = comparable_name(query)
    exact = [
        index
        for index, candidate in enumerate(candidates)
        if index != 0 and comparable_name(candidate.name) == wanted
    ]
    return [0, *exact][:_DETAIL_LIMIT]
