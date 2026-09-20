"""The MCP tools: thin wrappers over the services, one session per call."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from sqlmodel import Session

from ..db import session_scope
from ..errors import UsageError
from ..model import Disposition
from ..services import lists, reports, schema
from ..services.serialize import to_jsonable
from ..services.update_product import UpdateProductRequest, update_product


def _read(db_path: Path, function: Callable[..., Any], **arguments: Any) -> Any:
    """Run a read service in its own session, turning `UsageError` into a tool error."""
    try:
        with session_scope(db_path, migrate=False) as session:
            return to_jsonable(function(session, **arguments))
    except UsageError as error:
        raise ToolError(str(error)) from error


def register_tools(mcp: FastMCP, db_path: Path) -> None:
    @mcp.tool
    def list_unfiled(
        folder: str | None = None,
        root_id: int | None = None,
        recursive: bool = False,
        include_flagged: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        """The worklist: files nobody has filed yet, so you can work a folder at a time.

        With no `folder`, returns every folder that holds unfiled files, with
        `direct_files` (in that folder) and `subtree_files` (including subfolders)
        counts, per root. With a `folder` (relative to its root, e.g. "Blood and
        Bone/Core Rules"), returns that folder's own unfiled files, each with its
        text-analysis hint (a short description and a guess at its game system), plus
        its subfolders. Set `recursive` to get every file under the folder, which is
        how you file a product that spans subfolders. `root_id` is needed only when
        the same folder path exists under several roots.

        Files already resolved never appear: automatic duplicates, files missing from
        the share, and (unless `include_flagged`) files you deferred with a review
        flag. Use report_file for a file's full evidence.
        """
        return _read(
            db_path,
            lists.list_unfiled,
            folder=folder,
            root_id=root_id,
            recursive=recursive,
            include_flagged=include_flagged,
            limit=limit,
        )

    @mcp.tool
    def list_product_types() -> dict[str, Any]:
        """Every product type (a top-level function folder such as games or maps).

        Each has counts of its lines, products, and kept files. Call this at the start
        of a session: types are a fixed vocabulary, and you should almost always pick
        an existing one.
        """
        return _read(db_path, lists.list_product_types)

    @mcp.tool
    def list_product_lines(
        product_type: str | None = None, search: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Product lines (a game, a model line, a map publisher), with aliases.

        Filter by `product_type` name, and/or `search`, which matches names and
        aliases case-insensitively. ALWAYS search here before creating a line: a
        line must be the same coordinate across separate sessions, and "D&D 5e" and
        "Dungeons & Dragons" must not become two lines.
        """
        return _read(
            db_path,
            lists.list_product_lines,
            product_type=product_type,
            search=search,
            limit=limit,
        )

    @mcp.tool
    def report_file(file_id: int) -> dict[str, Any]:
        """Everything known about one file.

        Location and folder, disposition and product, embedded and per-media metadata,
        ISBN/ISSN/barcode, the text-analysis hint, all external evidence (ISBN record,
        DriveThruRPG, RPGGeek, Google search; each may be null), any errors, any open
        review flag, and `pending_changes`. The sampled page text is not returned: a
        model already read it and the hint is what it produced. Evidence is candidate
        signal, not a verdict; the folder path is often the strongest clue.
        """
        return _read(db_path, reports.report_file, file_id=file_id)

    @mcp.tool
    def report_product(
        product_id: int | None = None,
        product_type: str | None = None,
        product_line: str | None = None,
        product: str | None = None,
    ) -> dict[str, Any]:
        """One product: its details, line, type, files (with dispositions and hints),
        the folder its kept files go in, and `pending_changes`.

        Identify it by `product_id`, or by `product_type`, `product_line`, and
        `product` together.
        """
        return _read(
            db_path,
            reports.report_product,
            product_id=product_id,
            product_type=product_type,
            product_line=product_line,
            product=product,
        )

    @mcp.tool
    def report_line(
        line_id: int | None = None,
        product_type: str | None = None,
        product_line: str | None = None,
    ) -> dict[str, Any]:
        """One product line: its type, aliases, products (with file counts), and
        `pending_changes`.

        Identify it by `line_id`, or by `product_type` and `product_line` (a name or
        an alias).
        """
        return _read(
            db_path,
            reports.report_line,
            line_id=line_id,
            product_type=product_type,
            product_line=product_line,
        )

    @mcp.tool
    def describe_schema() -> dict[str, Any]:
        """The catalog's tables and columns, with notes and a few example queries.

        Use it before `query`. `file_text.sample_pages` is not for querying.
        """
        try:
            return to_jsonable(schema.describe_schema(db_path))
        except UsageError as error:
            raise ToolError(str(error)) from error

    @mcp.tool
    def query(sql: str, limit: int = 500) -> dict[str, Any]:
        """Run one read-only SQL SELECT (or WITH) against the catalog.

        For anything the other tools do not cover. At most 500 rows are returned
        (`truncated` says if there were more). Prefer list_unfiled and the report
        tools. Do not select `file_text.sample_pages`.
        """
        try:
            return to_jsonable(schema.run_readonly_query(db_path, sql, limit))
        except UsageError as error:
            raise ToolError(str(error)) from error

    @mcp.tool(name="update_product")
    def update_product_tool(
        file_ids: list[int],
        disposition: Literal["keep", "superseded", "discard", "unfiled"] | None = None,
        product_type: str | None = None,
        product_line: str | None = None,
        product: str | None = None,
        product_metadata: dict[str, str | None] | None = None,
        create_line: bool = False,
        create_type: bool = False,
        aliases: list[str] | None = None,
        review_flag: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record your judgment about a set of files. This is the only tool that writes.

        Pass many `file_ids` for one product in one call. It is a single transaction:
        if anything is invalid nothing changes and the error names what failed.

        `disposition`:
        - "keep": the files belong to a product. Requires `product_type`,
          `product_line`, and `product`.
        - "superseded": an older edition of a product. The coordinates are optional but
          all-or-none; giving them links the file to that product.
        - "discard": junk or unwanted.
        - "unfiled": undo an earlier decision (also clears the product link).

        Coordinates resolve by name, case-insensitively; a line also resolves by alias.
        An unknown type or line is REJECTED with the closest existing names unless you
        pass `create_line=true` (or `create_type=true`, which implies a new line).
        Search list_product_lines first. A type is a top-level folder, so create one
        only if truly needed. An unknown product name is created on the spot, with a
        warning if it looks like a typo of an existing product in that line.
        `aliases` adds alternate names to the resolved or created line.
        `product_metadata` may set publisher, year, artists, and description.

        To defer rather than guess, pass `review_flag` with a reason and no
        disposition: the file gets an open flag and drops off list_unfiled. A later
        keep, superseded, or discard resolves the flag; `note` records why.

        Automatic duplicates and files missing from the share cannot be filed.
        Nothing moves on the share until the user runs `reorganize`; the result's
        `target_folder` shows where the product's kept files will go.
        """
        request = UpdateProductRequest(
            file_ids=file_ids,
            disposition=Disposition(disposition) if disposition else None,
            product_type=product_type,
            product_line=product_line,
            product=product,
            product_metadata=product_metadata,
            create_line=create_line,
            create_type=create_type,
            aliases=aliases or [],
            review_flag=review_flag,
            note=note,
        )
        try:
            with session_scope(db_path, migrate=False) as session:
                return to_jsonable(_update(session, request))
        except UsageError as error:
            raise ToolError(str(error)) from error


def _update(session: Session, request: UpdateProductRequest) -> dict[str, Any]:
    return update_product(session, request)
