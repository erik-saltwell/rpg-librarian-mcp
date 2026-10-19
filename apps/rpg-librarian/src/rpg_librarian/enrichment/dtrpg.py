from __future__ import annotations

import asyncio
import os
import re

from rpg_librarian_tools.dtrpg import Product, search_products
from rpg_librarian_tools.errors import (
    AuthenticationError,
    RateLimitError,
    RemoteServiceError,
)

from ..model import DtrpgResult, ProcessingStage
from ..observability import log_file_fields
from .base import FatalSourceError
from .queries import (
    FileContext,
    is_product_document,
    name_ladder,
    pack_ladder,
    try_queries,
)

_ENV = "DTRPG_API_KEY"
_HITS = 5
_MAX_DESCRIPTION = 1000
# DriveThruRPG answers some queries with 400 instead of an empty list: the query
# cannot match, so it is a miss, and the next query in the ladder is tried.
_NOT_FOUND = 400
# A spaced "--" is one such query ("Personnel Files 3 -- Wild Justice"); as a single
# dash it finds the product.
_DASHES = re.compile(r"\s*-{2,}\s*")


class DtrpgSource:
    """DriveThruRPG catalog search by name, for product documents (PDFs) and packs."""

    name = "dtrpg"
    stage = ProcessingStage.dtrpg
    table = DtrpgResult

    def unavailable_reason(self) -> str | None:
        return None if os.environ.get(_ENV) else f"{_ENV} is not set"

    def begin_run(self) -> None:
        pass

    def wants(self, context: FileContext) -> bool:
        return is_product_document(context) or context.pack is not None

    def fetch(self, context: FileContext) -> DtrpgResult | None:
        ladder = pack_ladder(context.pack) if context.pack else name_ladder(context)
        queries = list(dict.fromkeys(_DASHES.sub(" - ", q) for q in ladder))
        if not queries:
            return None
        api_key = os.environ[_ENV]
        try:
            query, products = try_queries(queries, lambda q: _search(q, api_key))
        except (AuthenticationError, RateLimitError) as error:
            raise FatalSourceError(f"DriveThruRPG: {error!r}") from error
        log_file_fields(dtrpg_query=query)
        return DtrpgResult(
            query=query,
            results=[
                {
                    "product_id": product.product_id,
                    "title": product.title,
                    "description": product.description[:_MAX_DESCRIPTION],
                    "publisher": product.publisher,
                    "authors": list(product.authors),
                    "game_system": product.game_system,
                }
                for product in products
            ],
        )


def _search(query: str, api_key: str) -> tuple[Product, ...]:
    try:
        return asyncio.run(search_products(query, api_key, _HITS))
    except RemoteServiceError as error:
        if error.status_code == _NOT_FOUND:
            return ()
        raise
