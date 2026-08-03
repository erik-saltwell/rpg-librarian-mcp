"""resolve_review_flag -- close out an open review flag on one or more entries."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.ResolveReviewFlagCommand import ResolveReviewFlagCommand
from ..progress import McpProgressReporter


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool
    async def resolve_review_flag(
        path: Path,
        resolution_note: str,
        ctx: Context,
        process_recursively: bool = False,
    ) -> dict[str, object]:
        """Close the open review flag on every entry resolved from `path`,
        recording what the user decided.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. Entries with no open flag are
        skipped, not errored. This only records the decision -- if the
        user's instruction was to identify or reclassify the content, call
        `update_product`/`classify_content_role`/etc. separately; if the
        instruction was to leave it alone, this is the only call needed.
        """
        command = ResolveReviewFlagCommand(catalog, resolution_note)
        result = await command.process(
            path, process_recursively, False, McpProgressReporter(ctx)
        )
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
