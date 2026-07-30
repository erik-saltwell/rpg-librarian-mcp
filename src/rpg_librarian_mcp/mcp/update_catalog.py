from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.UpdateCatalogCommand import UpdateCatalogCommand


def register(mcp: FastMCP, catalog: Catalog) -> None:
    command = UpdateCatalogCommand(catalog)

    @mcp.tool
    async def update_catalog(
        path: Path,
        ctx: Context,
        process_recursively: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        """Scan a file or directory and update the catalog to match it.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. `force` bypasses the "skip if
        unchanged" check and reprocesses every matched file.
        """
        result = await command.process(path, process_recursively, force, ctx)
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
