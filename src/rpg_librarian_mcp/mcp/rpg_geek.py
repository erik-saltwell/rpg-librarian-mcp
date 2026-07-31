"""rpg_geek -- search and lookup RPG products via the RPGGeek API."""

from __future__ import annotations

from functools import lru_cache

from fastmcp import FastMCP

from ..catalog import Catalog
from ..commands.LookupRpgGeekProductCommand import LookupRpgGeekProductCommand
from ..commands.ProductLookupResult import ProductCandidate, ProductLookupDetails
from ..commands.SearchRpgGeekCommand import SearchRpgGeekCommand
from ..rpggeek import RpgGeekClient


@lru_cache(maxsize=1)
def _get_client() -> RpgGeekClient:
    """Lazily construct the RPGGeek client on first tool call.

    Deferred rather than built at server startup so a missing
    `RPGGEEK_BEARER_TOKEN` (or any other RPGGeek-specific issue) only
    breaks these two tools, not the whole server.
    """
    return RpgGeekClient()


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="search_rpg_geek")
    async def search_rpg_geek(
        name: str | None = None,
        isbn: str | None = None,
        max_values: int = 5,
    ) -> list[ProductCandidate]:
        """Search RPGGeek for candidate products by name and/or ISBN.

        At least one of `name` or `isbn` must be given; if both are given,
        `isbn` is tried first. Returns lightweight candidates -- use
        `lookup_rpg_geek_product` for full details on a chosen candidate.
        """
        command = SearchRpgGeekCommand(_get_client())
        return await command.run(name, isbn, max_values)

    @mcp.tool(name="lookup_rpg_geek_product")
    async def lookup_rpg_geek_product(rpggeek_id: int) -> ProductLookupDetails:
        """Fetch full product details for an RPGGeek item by its numeric id."""
        command = LookupRpgGeekProductCommand(_get_client())
        return await command.run(rpggeek_id)
