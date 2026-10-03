"""Schema discovery and the read-only SQL escape hatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..db import readonly_connection
from ..errors import UsageError

MAX_ROWS = 500

_DISALLOWED_LEADING_WORDS = frozenset(
    {
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
    }
)

_TABLE_NOTES = {
    "root": "A registered location: the library, or a staging dump folder.",
    "entry": (
        "A catalog item: the id the tools take. Either a file (type 'file', file_id "
        "set) or a pack (type 'pack', pack_id set). Its product lives here "
        "(product_id)."
    ),
    "file": (
        "One physical file occurrence. A loose file has its own entry (join "
        "entry.file_id = file.id) and its own disposition. A pack member has "
        "pack_id set and NO entry: join pack and entry (entry.pack_id = "
        "file.pack_id) for its pack's entry id, disposition, and product; its own "
        "disposition column is ignored (kept 'unfiled')."
    ),
    "pack": (
        "A set of files with one collective identity (a map pack, token set, audio "
        "set), filed as a whole. Holds the disposition; its entry (entry.pack_id) "
        "holds the product. original_root_path is the folder it was formed from; "
        "members move with reorganize. formation: 'find-packs' or 'create-pack'."
    ),
    "folder_judgment": (
        "What find-packs concluded about a folder (outcome: pack, container, "
        "no_packs, mixed, invalid, error), with its reason and details. mixed and "
        "invalid folders were left as loose files and need a person or create-pack."
    ),
    "folder_search": "find-packs's cached Google searches for folder names.",
    "product_type": "A top-level function folder: games, maps, ...",
    "product_line": "A game, model line, or publisher within one type.",
    "product_line_alias": "An alternate name for a line.",
    "product": "A set of files that shipped together, unique by name within its line.",
    "file_metadata": "Embedded properties (title, artist, ...) read from the file.",
    "file_text": (
        "Barcode, ISBN/ISSN (PDF only), and sample_pages (physical PDF pages "
        "or one logical plain-text sample at key '1', capped at 64 KiB of UTF-8). "
        "sample_pages is NOT for querying: a model already read it, and "
        "file_text_analysis holds the hint. Do not select it."
    ),
    "file_text_analysis": (
        "A model's description and possible_system guess from the sample "
        "(keyed by entry_id)."
    ),
    "isbn_result": (
        "Bibliographic record for the file's ISBN (evidence; keyed by file_id)."
    ),
    "dtrpg_result": "DriveThruRPG search hits (evidence; keyed by entry_id).",
    "rpggeek_result": "RPGGeek search candidates (evidence; keyed by entry_id).",
    "google_search_result": "Top Google hits (evidence; keyed by entry_id).",
    "error": (
        "A failed stage for an entry; cleared when it later succeeds. A pack's "
        "reorganize error summarizes all its members' failures."
    ),
    "review_flag": (
        "A deferral: the LLM could not place the entry. Open while resolved_at is null."
    ),
}

_EXAMPLE_QUERIES = [
    {
        "name": "files_needing_text_analysis",
        "description": "Entries with a text sample but no analysis yet.",
        "sql": (
            "SELECT e.id AS entry_id, f.relative_path FROM entry e "
            "JOIN file f ON f.id = e.file_id "
            "JOIN file_text t ON t.file_id = f.id "
            "LEFT JOIN file_text_analysis a ON a.entry_id = e.id "
            "WHERE a.entry_id IS NULL AND f.disposition = 'unfiled'"
        ),
    },
    {
        "name": "open_review_flags",
        "description": "Entries the LLM deferred and has not yet resolved.",
        "sql": (
            "SELECT r.entry_id, e.type, COALESCE(f.relative_path, "
            "p.original_root_path) AS path, r.reason FROM review_flag r "
            "JOIN entry e ON e.id = r.entry_id "
            "LEFT JOIN file f ON f.id = e.file_id "
            "LEFT JOIN pack p ON p.id = e.pack_id "
            "WHERE r.resolved_at IS NULL"
        ),
    },
    {
        "name": "unfiled_packs",
        "description": "Packs not yet filed, with their folder and member count.",
        "sql": (
            "SELECT e.id AS entry_id, p.original_root_path, "
            "(SELECT count(*) FROM file f WHERE f.pack_id = p.id) AS members "
            "FROM pack p JOIN entry e ON e.pack_id = p.id "
            "WHERE p.disposition = 'unfiled'"
        ),
    },
    {
        "name": "folders_find_packs_left_alone",
        "description": "Folders find-packs saw as packs but did not form.",
        "sql": (
            "SELECT j.root_id, j.folder, j.outcome, j.reason, j.details "
            "FROM folder_judgment j WHERE j.outcome IN ('mixed', 'invalid', 'error')"
        ),
    },
    {
        "name": "files_with_errors",
        "description": "Entries whose last attempt at some stage failed.",
        "sql": (
            "SELECT x.entry_id, e.type, COALESCE(f.relative_path, "
            "p.original_root_path) AS path, x.stage, x.error_text FROM error x "
            "JOIN entry e ON e.id = x.entry_id "
            "LEFT JOIN file f ON f.id = e.file_id "
            "LEFT JOIN pack p ON p.id = e.pack_id"
        ),
    },
]


def describe_schema(db_path: Path) -> dict[str, Any]:
    """Every table with its columns and a note, plus a few example queries."""
    with readonly_connection(db_path) as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' "
                "ORDER BY name"
            )
        ]
        tables = []
        for name in names:
            columns = [
                {
                    "name": c[1],
                    "type": c[2],
                    "not_null": bool(c[3]),
                    "primary_key": bool(c[5]),
                }
                for c in connection.execute(f'PRAGMA table_info("{name}")')
            ]
            tables.append(
                {"name": name, "note": _TABLE_NOTES.get(name), "columns": columns}
            )
    return {
        "tables": tables,
        "example_queries": _EXAMPLE_QUERIES,
        "notes": [
            "dispositions: unfiled, keep, duplicate, superseded, discard.",
            "Prefer list_unfiled, list_product_types, and list_product_lines over SQL.",
        ],
    }


def _has_extra_statement(sql: str) -> bool:
    """True if a `;` outside a quoted string splits this into several statements."""
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


def validate_readonly_sql(sql: str) -> None:
    trimmed = sql.strip()
    if not trimmed:
        raise UsageError("sql must not be empty.")
    if trimmed.split(None, 1)[0].upper() in _DISALLOWED_LEADING_WORDS:
        raise UsageError("Only SELECT or WITH statements are allowed.")
    if _has_extra_statement(trimmed):
        raise UsageError("Only a single SQL statement is allowed.")


def run_readonly_query(
    db_path: Path, sql: str, limit: int = MAX_ROWS
) -> dict[str, Any]:
    """Run one read-only statement; SQLite refuses writes on the connection anyway."""
    validate_readonly_sql(sql)
    if limit < 1:
        raise UsageError("limit must be at least 1.")
    cap = min(limit, MAX_ROWS)
    with readonly_connection(db_path) as connection:
        try:
            cursor = connection.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(cap + 1)
        except Exception as error:
            raise UsageError(f"SQL error: {error}") from error
    return {
        "columns": columns,
        "rows": [list(row) for row in rows[:cap]],
        "truncated": len(rows) > cap,
    }
