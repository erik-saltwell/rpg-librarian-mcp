"""Deletes both wide-event log files, starting each fresh and empty."""

from __future__ import annotations

from fastmcp import FastMCP

from ..catalog import Catalog
from ..observability import clear_logs as clear_logs_files


def register(mcp: FastMCP, config: Catalog) -> None:
    @mcp.tool(name="clear_logs")
    def clear_logs() -> dict[str, bool]:
        """Delete `tool_calls.log` and `entry_processing.log`, then reopen
        fresh empty files in their place. No locking -- just deletes and
        gets out."""
        return clear_logs_files(config.catalog_dir)
