from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

_MAX_REPORTED_ENTRIES = 20
_ERRORED_ENTRIES_WHERE = "json_array_length(errors) > 0"


@dataclass(frozen=True)
class PurgeStats:
    removed: int
    removed_filepaths: list[str] = field(default_factory=list)


def purge_errors(conn: sqlite3.Connection) -> PurgeStats:
    """Delete every catalog entry that has one or more recorded errors
    (`entries.errors` is a non-empty JSON array), along with its media-type
    side-table row and OCR text via cascade. Does not resync -- the row is
    simply gone, so the next `sync_catalog` run treats the file as new and
    reprocesses it from scratch. Useful after fixing an extraction bug so
    previously-failed files get a fresh attempt instead of keeping their
    stale, error-flagged row forever."""
    rows = conn.execute(f"SELECT id, filepath FROM entries WHERE {_ERRORED_ENTRIES_WHERE}").fetchall()  # noqa: S608

    with conn:
        # entry_text is an FTS5 virtual table, which can't declare a real
        # FOREIGN KEY -- ON DELETE CASCADE on entries does not reach it, so
        # it needs an explicit delete alongside the entries delete (the
        # media-type side tables below it *do* cascade correctly).
        conn.executemany("DELETE FROM entry_text WHERE entry_id = ?", [(row["id"],) for row in rows])
        conn.execute(f"DELETE FROM entries WHERE {_ERRORED_ENTRIES_WHERE}")  # noqa: S608

    return PurgeStats(
        removed=len(rows),
        removed_filepaths=[row["filepath"] for row in rows[:_MAX_REPORTED_ENTRIES]],
    )
