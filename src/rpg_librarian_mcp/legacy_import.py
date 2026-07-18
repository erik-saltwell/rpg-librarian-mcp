"""One-time migration from the legacy rpg-librarian JSON catalog
(`.catalog/index.json` + `.catalog/products.json` + `.catalog/text_fragments/`)
into the new SQLite schema.

Deliberately not exposed as an MCP tool: this is a single manual step run once
per legacy library, not part of the ongoing Claude-Code-driven workflow. Run
it directly:

    uv run rpg-librarian-legacy-import /path/to/legacy/library

The target catalog is resolved the same way the MCP server resolves it: under
`.catalog/` beneath the current working directory. `cd` into the new library
root first.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import db
from .schema import ENTRIES, MEDIA_METADATA_TABLES, PRODUCTS
from .sql_helpers import upsert

_MAX_REPORTED_SKIPS = 20


@dataclass
class LegacyImportStats:
    products_imported: int = 0
    entries_imported: int = 0
    entries_skipped: int = 0
    text_fragments_imported: int = 0
    skip_reasons: list[str] = field(default_factory=list)

    def record_skip(self, entry_id: str, reason: str) -> None:
        self.entries_skipped += 1
        if len(self.skip_reasons) < _MAX_REPORTED_SKIPS:
            self.skip_reasons.append(f"{entry_id}: {reason}")


def _normalize(path_str: str) -> str:
    """Windows or POSIX path string -> forward-slash-separated string, so
    migration works regardless of which OS wrote the legacy JSON or which OS
    is running the migration."""
    return path_str.replace("\\", "/")


def _relative_to_root(path_str: str, root_norm: str) -> str:
    """Make a legacy (possibly absolute) path library-root-relative, since the
    new catalog is portable and never bakes in an absolute source path."""
    norm = _normalize(path_str)
    root_prefix = root_norm.rstrip("/") + "/"
    if norm.lower().startswith(root_prefix.lower()):
        return norm[len(root_prefix) :]
    return norm.lstrip("/")


def _legacy_entry_path(entry: dict[str, Any]) -> str | None:
    if entry.get("filepath"):
        return entry["filepath"]
    file_data = entry.get("file_data")
    if file_data and file_data.get("filepath"):
        return file_data["filepath"]
    return None


def _build_product_folder_index(products: list[dict[str, Any]], root_norm: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for product in products:
        rel_folder = _relative_to_root(product["folder"], root_norm)
        index[rel_folder] = product["id"]
    return index


def _find_product_id(rel_filepath: str, folder_index: dict[str, str]) -> str | None:
    """The deepest product folder that is an ancestor of the file, if any."""
    for ancestor in PurePosixPath(rel_filepath).parents:
        candidate = str(ancestor) if str(ancestor) != "." else ""
        if candidate in folder_index:
            return folder_index[candidate]
    return None


def _map_product(product: dict[str, Any], root_norm: str) -> dict[str, Any]:
    return {
        "id": product["id"],
        "folder": _relative_to_root(product["folder"], root_norm),
        "title": product.get("title"),
        "publisher": product.get("publisher"),
        "author": product.get("author"),
        "url": product.get("url"),
        "description": product.get("description"),
        "system": None,
        "category": None,
        "source": product.get("source"),
        "no_match": bool(product.get("no_match", False)),
        "errors": product.get("errors", []),
        "created_at": product.get("created_at") or db.now_iso(),
        "updated_at": product.get("updated_at") or db.now_iso(),
    }


def _map_entry(
    entry: dict[str, Any], rel_filepath: str, root_norm: str, folder_index: dict[str, str]
) -> dict[str, Any] | None:
    file_data = entry.get("file_data") or {}
    base_metadata = entry.get("base_metadata") or {}

    sha256 = file_data.get("sha256")
    size_in_bytes = file_data.get("size_in_bytes")
    if sha256 is None or size_in_bytes is None:
        return None

    rel_path = PurePosixPath(rel_filepath)
    parent_folder = file_data.get("parent_folder") or (rel_path.parent.name or None)
    grandparent_folder = file_data.get("grandparent_folder") or (rel_path.parent.parent.name or None)

    return {
        "id": entry["id"],
        "filepath": rel_filepath,
        "filename": file_data.get("filename") or rel_path.name,
        "extension": file_data.get("extension") or rel_path.suffix,
        "parent_folder": parent_folder,
        "grandparent_folder": grandparent_folder,
        "size_in_bytes": size_in_bytes,
        "mtime": None,
        "sha256": sha256,
        "mime_type": entry.get("mime_type") or file_data.get("mime_type"),
        "media_type": entry.get("media_type") or "unknown",
        "product_id": _find_product_id(rel_filepath, folder_index),
        "artist": base_metadata.get("artist"),
        "title": base_metadata.get("title"),
        "publisher": base_metadata.get("publisher"),
        "copyright": base_metadata.get("copyright"),
        "genre": base_metadata.get("genre"),
        "system": base_metadata.get("system"),
        "description": base_metadata.get("description"),
        "url": base_metadata.get("url"),
        "isbn": base_metadata.get("isbn"),
        "issn": base_metadata.get("issn"),
        "barcode": base_metadata.get("barcode"),
        "source": base_metadata.get("source"),
        "llm_no_match": bool(base_metadata.get("llm_no_match", False)),
        "match_source": entry.get("match_source"),
        "match_found": entry.get("match_found"),
        "errors": entry.get("errors", []),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
    }


def _map_media_type_metadata(media_type: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    metadata_info = MEDIA_METADATA_TABLES.get(media_type)
    if metadata_info is None:
        return None
    _, table = metadata_info
    known_columns = set(table.columns) - {"entry_id"}
    # Filters out any legacy/removed fields (e.g. audio's old acoustic_fingerprint,
    # image's old hash) that no longer have a column in the new schema.
    return {key: value for key, value in raw.items() if key in known_columns}


def _load_text_fragment(text_fragments_dir: Path, entry_id: str) -> str | None:
    fragment_path = text_fragments_dir / f"{entry_id}.json"
    if not fragment_path.exists():
        return None
    data = json.loads(fragment_path.read_text(encoding="utf-8"))
    pages = data.get("pages", [])
    text = "\n\n".join(page.get("text", "") for page in pages).strip()
    return text or None


def import_legacy_catalog(conn: sqlite3.Connection, legacy_library_root: Path) -> LegacyImportStats:
    catalog_dir = legacy_library_root / ".catalog"
    index = json.loads((catalog_dir / "index.json").read_text(encoding="utf-8"))
    products_data = json.loads((catalog_dir / "products.json").read_text(encoding="utf-8"))
    text_fragments_dir = catalog_dir / "text_fragments"

    root_norm = _normalize(index["library"]["root_folder"])
    stats = LegacyImportStats()

    folder_index = _build_product_folder_index(products_data.get("products", []), root_norm)

    with conn:
        for product in products_data.get("products", []):
            upsert(conn, "products", PRODUCTS, _map_product(product, root_norm))
            stats.products_imported += 1

        for entry in index.get("entries", []):
            legacy_path = _legacy_entry_path(entry)
            if legacy_path is None:
                stats.record_skip(entry["id"], "no filepath (neither entry.filepath nor file_data.filepath)")
                continue

            rel_filepath = _relative_to_root(legacy_path, root_norm)
            mapped_entry = _map_entry(entry, rel_filepath, root_norm, folder_index)
            if mapped_entry is None:
                stats.record_skip(entry["id"], "missing file_data.sha256/size_in_bytes")
                continue

            upsert(conn, "entries", ENTRIES, mapped_entry)
            stats.entries_imported += 1

            metadata = _map_media_type_metadata(mapped_entry["media_type"], entry.get("media_type_metadata"))
            metadata_info = MEDIA_METADATA_TABLES.get(mapped_entry["media_type"])
            if metadata_info is not None and metadata is not None:
                table_name, table = metadata_info
                row = dict(metadata)
                row["entry_id"] = mapped_entry["id"]
                upsert(conn, table_name, table, row)

            text = _load_text_fragment(text_fragments_dir, entry["id"])
            if text is not None:
                conn.execute("DELETE FROM entry_text WHERE entry_id = ?", (mapped_entry["id"],))
                conn.execute(
                    "INSERT INTO entry_text (entry_id, content) VALUES (?, ?)",
                    (mapped_entry["id"], text),
                )
                stats.text_fragments_imported += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "legacy_library_root",
        type=Path,
        help="Path to the old rpg-librarian library root (the directory containing .catalog/index.json).",
    )
    args = parser.parse_args()

    conn = db.connect()
    try:
        stats = import_legacy_catalog(conn, args.legacy_library_root)
    finally:
        conn.close()

    print(f"Products imported:       {stats.products_imported}")
    print(f"Entries imported:        {stats.entries_imported}")
    print(f"Entries skipped:         {stats.entries_skipped}")
    print(f"Text fragments imported: {stats.text_fragments_imported}")
    if stats.skip_reasons:
        print("\nFirst skipped entries:")
        for reason in stats.skip_reasons:
            print(f"  - {reason}")


if __name__ == "__main__":
    main()
