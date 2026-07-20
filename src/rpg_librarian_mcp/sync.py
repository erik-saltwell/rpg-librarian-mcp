from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import db
from .extractors import EXTRACTORS
from .extractors.detect import find_mime_type, media_type_for_mime
from .library_docs import DOC_FILENAMES, ensure_library_docs
from .schema import ENTRIES, MEDIA_METADATA_TABLES
from .sql_helpers import row_to_dict, upsert

_EXCLUDED_FILENAMES = set(DOC_FILENAMES)
_MAX_REPORTED_ERRORS = 20
_HASH_CHUNK_SIZE = 1024 * 1024


@dataclass
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    errored: int = 0
    error_details: list[str] = field(default_factory=list)
    docs_created: list[str] = field(default_factory=list)

    def record_error(self, filepath: str, reason: str) -> None:
        self.errored += 1
        if len(self.error_details) < _MAX_REPORTED_ERRORS:
            self.error_details.append(f"{filepath}: {reason}")


def _is_excluded_filename(filename: str) -> bool:
    return filename.lower() in _EXCLUDED_FILENAMES


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_catalog(conn: sqlite3.Connection, library_root: Path | None = None) -> SyncStats:
    """Walk `library_root` (default cwd), ensure every non-excluded file has a
    catalog entry with type-specific metadata, and remove entries for files
    that no longer exist. New files are added; existing files are re-hashed/
    re-extracted only if their mtime changed since the last sync; unchanged
    files are skipped without touching disk beyond a stat() call. Does not
    touch product_id, ISBN/LLM lookup fields, or OCR text -- those belong to
    separate tools. Also writes claude.md/agents.md at the library root if
    they don't already exist yet (never overwrites either)."""
    library_root = (library_root or Path.cwd()).resolve()
    (db.catalog_dir(library_root) / "text_fragments").mkdir(parents=True, exist_ok=True)

    stats = SyncStats()
    stats.docs_created = ensure_library_docs(library_root)
    existing_rows = {row["filepath"]: row_to_dict(row, ENTRIES) for row in conn.execute("SELECT * FROM entries")}
    seen_filepaths: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(library_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if _is_excluded_filename(filename):
                continue

            full_path = Path(dirpath) / filename
            rel_path = full_path.relative_to(library_root).as_posix()
            seen_filepaths.add(rel_path)

            try:
                stat = full_path.stat()
            except OSError as exc:
                stats.record_error(rel_path, f"stat failed: {exc}")
                continue
            mtime = stat.st_mtime

            prior = existing_rows.get(rel_path)
            if prior is not None and prior["mtime"] == mtime:
                stats.unchanged += 1
                continue

            is_new = prior is None
            entry_id = prior["id"] if prior is not None else str(uuid.uuid4())

            try:
                extraction_error = _sync_one_file(
                    conn, full_path, rel_path, entry_id, mtime, stat.st_size, prior
                )
            except Exception as exc:
                stats.record_error(rel_path, f"could not process file: {exc}")
                continue

            if is_new:
                stats.added += 1
            else:
                stats.updated += 1
            if extraction_error is not None:
                stats.record_error(rel_path, extraction_error)

    missing_filepaths = set(existing_rows) - seen_filepaths
    for filepath in missing_filepaths:
        entry_id = existing_rows[filepath]["id"]
        # entry_text is an FTS5 virtual table and can't declare a real
        # FOREIGN KEY, so ON DELETE CASCADE on entries doesn't reach it --
        # needs an explicit delete (the media-type side tables do cascade).
        conn.execute("DELETE FROM entry_text WHERE entry_id = ?", (entry_id,))
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.commit()
        stats.removed += 1

    return stats


def _sync_one_file(
    conn: sqlite3.Connection,
    full_path: Path,
    rel_path: str,
    entry_id: str,
    mtime: float,
    size_in_bytes: int,
    prior: dict[str, Any] | None,
) -> str | None:
    """Hash/detect/extract one file and upsert its entries + side-table rows.
    Returns an error message if type-specific extraction failed (the entries
    row is still written from the mechanical fields alone), or None on full
    success. A failure in the mechanical part itself (hashing, mime
    detection) is allowed to raise -- that's a whole-file failure with no row
    written at all, handled by the caller."""
    sha256 = _hash_file(full_path)
    mime_type = find_mime_type(full_path)
    media_type = media_type_for_mime(mime_type, full_path.suffix)

    # Seed from the prior row (if any) so fields this command doesn't own --
    # product_id, isbn/issn/barcode, source, llm_no_match, match_source/found
    # -- survive an update untouched; only the mechanical + extracted fields
    # below are overlaid.
    entry_data: dict[str, Any] = dict(prior) if prior is not None else {}
    entry_data.update(
        {
            "id": entry_id,
            "filepath": rel_path,
            "filename": full_path.name,
            "extension": full_path.suffix,
            "parent_folder": full_path.parent.name or None,
            "grandparent_folder": full_path.parent.parent.name or None,
            "size_in_bytes": size_in_bytes,
            "mtime": mtime,
            "sha256": sha256,
            "mime_type": mime_type,
            "media_type": media_type,
            "errors": [],
        }
    )

    extractor = EXTRACTORS.get(media_type)
    media_type_metadata: dict[str, Any] | None = None
    extraction_error: str | None = None
    if extractor is not None:
        try:
            result = extractor(full_path)
            media_type_metadata = result.media_type_metadata
            entry_data.update(result.base_metadata)
        except Exception as exc:
            extraction_error = f"extraction failed: {exc}"
            entry_data["errors"] = [extraction_error]

    entry_data["updated_at"] = db.now_iso()
    if prior is None:
        entry_data["created_at"] = db.now_iso()

    upsert(conn, "entries", ENTRIES, entry_data)

    if extractor is not None:
        table_name, table = MEDIA_METADATA_TABLES[media_type]
        row = dict(media_type_metadata or {})
        row["entry_id"] = entry_id
        upsert(conn, table_name, table, row)

    conn.commit()
    return extraction_error
