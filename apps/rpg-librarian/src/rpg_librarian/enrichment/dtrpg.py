from __future__ import annotations

import asyncio
import os

from rpg_librarian_tools.dtrpg import search_products
from rpg_librarian_tools.errors import AuthenticationError, RateLimitError

from ..model import DtrpgResult, ProcessingStage
from ..model.core import FileMetadataBase
from ..observability import log_file_fields
from .base import FatalSourceError
from .queries import FileContext, is_product_document, name_ladder, try_queries

_ENV = "DTRPG_API_KEY"
_HITS = 5
_MAX_DESCRIPTION = 1000


class DtrpgSource:
    """DriveThruRPG catalog search by name, for product documents (PDFs) only."""

    name = "dtrpg"
    stage = ProcessingStage.dtrpg
    table = DtrpgResult

    def unavailable_reason(self) -> str | None:
        return None if os.environ.get(_ENV) else f"{_ENV} is not set"

    def begin_run(self) -> None:
        pass

    def wants(self, context: FileContext) -> bool:
        return is_product_document(context)

    def fetch(self, context: FileContext) -> FileMetadataBase | None:
        queries = name_ladder(context)
        if not queries:
            return None
        api_key = os.environ[_ENV]
        try:
            query, products = try_queries(
                queries,
                lambda q: asyncio.run(search_products(q, api_key, _HITS)),
            )
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
