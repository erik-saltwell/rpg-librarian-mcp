"""classify_content_role -- classify each entry's product into a content role."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.ClassifyContentRoleCommand import ClassifyContentRoleCommand


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool
    async def classify_content_role(
        path: Path,
        ctx: Context,
        process_recursively: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        """Classify each entry's product into a content role using an LLM
        judgment over the product's description and any linked PDFs'
        sample text.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. `force` reclassifies products that
        already have a content_role. Entries with no product, products
        whose system is "Agnostic" (no role tier applies to system-agnostic
        content), and products with no description or sample text to
        classify from are skipped, not errored -- run `lookup_isbn`,
        `lookup_rpg_geek_product`, or `read_pdfs` first to give a product
        text to classify from.

        Roles: core_rules, adventures_and_scenarios,
        settings_and_supplements, gm_and_player_aids, extras.
        """
        command = ClassifyContentRoleCommand(catalog)
        result = await command.process(path, process_recursively, force, ctx)
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
