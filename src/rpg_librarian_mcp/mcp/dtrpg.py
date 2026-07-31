"""dtrpg -- search DriveThruRPG's catalog or the caller's purchased library."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastmcp import FastMCP

from ..catalog import Catalog
from ..commands.ProductLookupResult import ProductLookupDetails
from ..commands.SearchDtrpgCommand import SearchDtrpgCommand
from ..dtrpg import DriveThruRPGClient


@lru_cache(maxsize=1)
def _get_client() -> DriveThruRPGClient:
    """Lazily construct the DriveThruRPG client on first tool call.

    Deferred rather than built at server startup -- `DriveThruRPGClient`
    requires `DTRPG_API_KEY` and authenticates over the network immediately
    in `__init__`, which would otherwise crash the whole server on a
    missing/invalid key instead of just this tool.
    """
    return DriveThruRPGClient()


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="search_dtrpg")
    def search_dtrpg(
        query: str,
        scope: Literal["library", "catalog"] = "catalog",
        max_values: int = 10,
    ) -> list[ProductLookupDetails]:
        """Search DriveThruRPG for products matching `query`, returning full
        details per result.

        `scope="catalog"` (default) searches all of DriveThruRPG;
        `scope="library"` searches only products the caller has already
        purchased.
        """
        command = SearchDtrpgCommand(_get_client())
        return command.run(query, scope, max_values)
