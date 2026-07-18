from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

CATALOG_DIR_NAME = ".catalog"
DB_FILE_NAME = "catalog.db"


def now_iso() -> str:
    """Current UTC time in the same format as the schema's SQL-side
    `strftime('%Y-%m-%dT%H:%M:%fZ', 'now')` defaults, so Python-supplied
    timestamps (e.g. from migrations) match rows created by SQL defaults."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def catalog_dir(library_root: Path | None = None) -> Path:
    """The `.catalog` directory for a library, resolved relative to `cwd` by
    default -- the library root is wherever Claude Code was launched from."""
    return (library_root or Path.cwd()) / CATALOG_DIR_NAME


def db_path(library_root: Path | None = None) -> Path:
    return catalog_dir(library_root) / DB_FILE_NAME


def _sql_scripts_dir() -> Path:
    # src/rpg_librarian_mcp/db.py -> repo root -> sql_scripts
    return Path(__file__).resolve().parent.parent.parent / "sql_scripts"


def connect(library_root: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the library's catalog database, creating the
    `.catalog` directory and initializing the schema on first use."""
    path = db_path(library_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + NORMAL sync: commits stay cheap (no fsync per commit) while still
    # being crash-safe against process interruption, so callers doing a long
    # walk over many files (e.g. sync_catalog) can commit after every file
    # instead of batching, without eating a full fsync cost per file.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    already_initialized = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
    ).fetchone()
    if already_initialized is not None:
        return
    script = (_sql_scripts_dir() / "create_schema.sql").read_text(encoding="utf-8")
    conn.executescript(script)
    conn.commit()
