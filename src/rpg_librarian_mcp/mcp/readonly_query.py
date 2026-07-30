"""Escape-hatch ad-hoc read-only SQL access to the catalog db."""

from __future__ import annotations

from fastmcp import FastMCP

from ..catalog import Catalog
from ..db import readonly_connection

_DISALLOWED_LEADING_WORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "PRAGMA",
    "ATTACH",
    "DETACH",
    "VACUUM",
    "REINDEX",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "RELEASE",
    "ANALYZE",
)
_MAX_LIMIT = 500


def _has_disallowed_semicolon(sql: str) -> bool:
    """True if a `;` splits this into more than one statement.

    A single trailing `;` is tolerated (stripped first); any `;` found after
    that, outside a single-quoted string literal, means a second statement
    is present.
    """
    stripped = sql.rstrip()
    if stripped.endswith(";"):
        stripped = stripped[:-1]

    in_string = False
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char == "'":
            if in_string and stripped[index + 1 : index + 2] == "'":
                index += 2
                continue
            in_string = not in_string
        elif char == ";" and not in_string:
            return True
        index += 1
    return False


def _validate_statement(sql: str) -> None:
    trimmed = sql.strip()
    if not trimmed:
        raise ValueError("sql must not be empty")
    first_word = trimmed.split(None, 1)[0].upper()
    if first_word in _DISALLOWED_LEADING_WORDS:
        raise ValueError("only SELECT or WITH statements are allowed")
    if _has_disallowed_semicolon(trimmed):
        raise ValueError("only a single SQL statement is allowed")


def run_readonly_query(
    catalog: Catalog, sql: str, limit: int = 500
) -> dict[str, object]:
    """Run one read-only SQL statement against the catalog db, return the result."""
    _validate_statement(sql)
    if limit < 1:
        raise ValueError(f"limit must be a positive integer, got {limit}")
    effective_limit = min(limit, _MAX_LIMIT)

    with readonly_connection(catalog) as conn:
        cursor = conn.execute(sql)
        columns = (
            [description[0] for description in cursor.description]
            if cursor.description
            else []
        )
        rows = cursor.fetchmany(effective_limit + 1)

    truncated = len(rows) > effective_limit
    return {
        "columns": columns,
        "rows": [list(row) for row in rows[:effective_limit]],
        "truncated": truncated,
    }


def get_catalog_schema(catalog: Catalog) -> dict[str, object]:
    """The DDL of every domain table in the catalog db."""
    with readonly_connection(catalog) as conn:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        ).fetchall()
    return {"tables": [{"name": name, "sql": sql} for name, sql in rows]}


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="run_readonly_query")
    def run_readonly_query_tool(sql: str, limit: int = 500) -> dict[str, object]:
        """Run one read-only SQL statement against the catalog db, return the result."""
        return run_readonly_query(catalog, sql, limit)

    @mcp.tool(name="get_catalog_schema")
    def get_catalog_schema_tool() -> dict[str, object]:
        """The DDL of every domain table in the catalog db."""
        return get_catalog_schema(catalog)
