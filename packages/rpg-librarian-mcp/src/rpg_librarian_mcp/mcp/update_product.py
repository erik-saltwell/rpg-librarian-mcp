"""update_product -- find or create a Product from given details, then link entries."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.UpdateProductCommand import UpdateProductCommand
from ..model import IdentificationMethod
from ..progress import McpProgressReporter


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool
    async def update_product(
        path: Path,
        title: str,
        identification_method: IdentificationMethod,
        ctx: Context,
        process_recursively: bool = False,
        description: str | None = None,
        artists: str | None = None,
        publisher: str | None = None,
        year: str | None = None,
        system: str | None = None,
    ) -> dict[str, object]:
        """Find or create a Product matching the given details, then link
        every entry under `path` to it.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set (ignored for a single file). `title`
        is required; other Product fields are optional.
        `identification_method` records how this product was identified
        (e.g. `manual`, `isbn_match`, `rpggeek_match`) -- there is no
        default, always state it explicitly.

        Existing products are matched case-insensitively on every field
        actually passed (omitted fields are not constrained); zero matches
        creates a new `Product`, one match reuses it as-is, and more than
        one match raises -- pass more distinguishing fields (e.g. `system`)
        to disambiguate. Raises if `path` resolves to no cataloged entries
        at all (run `update_catalog` first).
        """
        command = UpdateProductCommand(catalog)
        result, product_id, created = await command.run(
            path,
            process_recursively,
            title,
            identification_method,
            McpProgressReporter(ctx),
            description=description,
            artists=artists,
            publisher=publisher,
            year=year,
            system=system,
        )
        return {
            **result._asdict(),
            "errors": [e._asdict() for e in result.errors],
            "product_id": str(product_id),
            "created": created,
        }
