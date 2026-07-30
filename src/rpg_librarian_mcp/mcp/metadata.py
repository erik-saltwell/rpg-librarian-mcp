"""metadata -- extract and persist raw, per-source metadata for a file or directory."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.UpdateMetadataCommand import UpdateMetadataCommand
from ..model import ProcessingStage


def register(mcp: FastMCP, catalog: Catalog) -> None:
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    @mcp.tool
    async def update_metadata(
        path: Path,
        ctx: Context,
        process_recursively: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        """Extract and persist raw metadata for a file or directory of files.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. `force` bypasses the "skip if
        unchanged" check and reprocesses every matched file.
        """
        result = await command.process(path, process_recursively, force, ctx)
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
