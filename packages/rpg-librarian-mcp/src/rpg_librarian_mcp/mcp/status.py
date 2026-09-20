"""Reports server version and configured library location."""

from __future__ import annotations

from fastmcp import FastMCP

from .. import __version__
from ..catalog import Catalog


def register(mcp: FastMCP, config: Catalog) -> None:
    @mcp.tool
    def librarian_status() -> dict[str, object]:
        """Report the server version and the library it is pointed at."""
        return {
            "version": __version__,
            "library_root": str(config.library_root),
            "catalog_dir": str(config.catalog_dir),
            "catalog_exists": config.catalog_dir.is_dir(),
        }
