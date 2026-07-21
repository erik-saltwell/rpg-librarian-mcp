"""Basic status tool -- also the template for further tool modules."""

from __future__ import annotations

from fastmcp import FastMCP

from .. import __version__
from ..config import Config


def register(mcp: FastMCP, config: Config) -> None:
    @mcp.tool
    def librarian_status() -> dict[str, object]:
        """Report the server version and the library it is pointed at."""
        return {
            "version": __version__,
            "library_root": str(config.library_root),
            "catalog_dir": str(config.catalog_dir),
            "catalog_exists": config.catalog_dir.is_dir(),
        }
