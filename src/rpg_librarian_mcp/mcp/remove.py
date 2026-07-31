"""remove -- move entries under a path to .catalog/trash/, dropping the catalog rows."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.RemoveCommand import RemoveCommand


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool
    async def remove(
        path: Path,
        ctx: Context,
        process_recursively: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        """Move every cataloged entry under `path` (or `path` itself, if
        it's a single file) into `.catalog/trash/`, removing it from the
        catalog.

        Not a delete -- each file is relocated on disk, mirroring its
        library-relative path under `.catalog/trash/` (intermediate
        directories created as needed), and its Entry row is removed.
        `path` must be an absolute path; directories are non-recursive
        unless `process_recursively` is set. `force` has no effect here --
        every resolved entry is always removed, there's no stale-result
        concept to bypass.
        """
        command = RemoveCommand(catalog)
        result = await command.process(path, process_recursively, force, ctx)
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
