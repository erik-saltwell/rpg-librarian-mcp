"""flag_for_review -- raise a human-review flag on one or more entries."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.FlagForReviewCommand import FlagForReviewCommand


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool
    async def flag_for_review(
        path: Path,
        reason: str,
        ctx: Context,
        process_recursively: bool = False,
    ) -> dict[str, object]:
        """Raise an open review flag on every entry resolved from `path`,
        asking a human to look at it -- use this instead of guessing when
        you can't identify a product, are torn between candidates, or
        otherwise want to defer a decision.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. All resolved entries share the one
        `reason` given -- to flag every file belonging to one product,
        point `path` at the product's directory (or pass
        `process_recursively=True` for a deeper layout) rather than calling
        this once per file.

        Re-flagging an entry that already has an open flag updates its
        `reason` in place rather than creating a duplicate. Resolve a flag
        with `resolve_review_flag` once the user has said how to handle it.
        """
        command = FlagForReviewCommand(catalog, reason)
        result = await command.process(path, process_recursively, False, ctx)
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
