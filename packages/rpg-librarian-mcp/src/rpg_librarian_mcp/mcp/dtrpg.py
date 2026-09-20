"""dtrpg -- search DriveThruRPG's catalog or the caller's purchased library."""

from __future__ import annotations

import os
from typing import Literal

from fastmcp import FastMCP

from ..catalog import Catalog
from ..commands.ProductLookupResult import ProductLookupDetails
from ..commands.SearchDtrpgCommand import SearchDtrpgCommand


def _api_key() -> str:
    value = os.environ.get("DTRPG_API_KEY")
    if not value:
        raise ValueError("DTRPG_API_KEY is not set")
    return value


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="search_dtrpg")
    async def search_dtrpg(
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
        command = SearchDtrpgCommand(_api_key())
        return await command.run(query, scope, max_values)
