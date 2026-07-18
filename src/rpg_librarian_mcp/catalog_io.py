from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .schema import ENTRIES, MEDIA_METADATA_TABLES, PRODUCTS
from .sql_helpers import row_to_dict, upsert

SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True)
class ImportStats:
    products: int
    entries: int


def _schema_version(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (SCHEMA_VERSION_KEY,)).fetchone()
    return row["value"] if row else "unknown"


def export_catalog(conn: sqlite3.Connection) -> dict[str, Any]:
    """Export the full catalog -- products, entries, per-media-type metadata,
    and OCR text -- as a single JSON-serializable dict."""
    products = [row_to_dict(row, PRODUCTS) for row in conn.execute("SELECT * FROM products ORDER BY id")]

    entries = []
    for row in conn.execute("SELECT * FROM entries ORDER BY id"):
        entry = row_to_dict(row, ENTRIES)
        metadata_info = MEDIA_METADATA_TABLES.get(entry["media_type"])
        if metadata_info is not None:
            table_name, table = metadata_info
            meta_row = conn.execute(
                f"SELECT * FROM {table_name} WHERE entry_id = ?",  # noqa: S608 (table_name from fixed internal mapping)
                (entry["id"],),
            ).fetchone()
            if meta_row is not None:
                metadata = row_to_dict(meta_row, table)
                metadata.pop("entry_id", None)
                entry["media_type_metadata"] = metadata
        text_row = conn.execute("SELECT content FROM entry_text WHERE entry_id = ?", (entry["id"],)).fetchone()
        if text_row is not None:
            entry["text"] = text_row["content"]
        entries.append(entry)

    return {
        "schema_version": _schema_version(conn),
        "exported_at": datetime.now(UTC).isoformat(),
        "products": products,
        "entries": entries,
    }


def import_catalog(conn: sqlite3.Connection, data: dict[str, Any]) -> ImportStats:
    """Import a dict as produced by `export_catalog`, upserting rows by id.
    An entry/product already present with a matching id is overwritten;
    everything else in the database is left untouched."""
    products = data.get("products", [])
    entries = data.get("entries", [])

    with conn:
        for product in products:
            upsert(conn, "products", PRODUCTS, product)

        for entry in entries:
            entry = dict(entry)
            metadata = entry.pop("media_type_metadata", None)
            text = entry.pop("text", None)
            upsert(conn, "entries", ENTRIES, entry)

            metadata_info = MEDIA_METADATA_TABLES.get(entry.get("media_type"))
            if metadata_info is not None and metadata is not None:
                table_name, table = metadata_info
                row = dict(metadata)
                row["entry_id"] = entry["id"]
                upsert(conn, table_name, table, row)

            conn.execute("DELETE FROM entry_text WHERE entry_id = ?", (entry["id"],))
            if text is not None:
                conn.execute(
                    "INSERT INTO entry_text (entry_id, content) VALUES (?, ?)",
                    (entry["id"], text),
                )

    return ImportStats(products=len(products), entries=len(entries))
