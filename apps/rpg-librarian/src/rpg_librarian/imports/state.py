"""Private SQLite journal beside the catalog; provenance survives catalog cleaning."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..errors import UsageError

SCHEMA = """

CREATE TABLE IF NOT EXISTS setting(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS remote(
 id TEXT PRIMARY KEY, parent TEXT, name TEXT, kind TEXT NOT NULL,
 size INTEGER NOT NULL, version TEXT NOT NULL, etag TEXT, data TEXT NOT NULL,
 deleted INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL,
 path TEXT, group_id TEXT, eligible INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS folder_group(
 id TEXT PRIMARY KEY, path TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0,
 fresh INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT 'queued',
 attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS revision(
 id INTEGER PRIMARY KEY, remote_id TEXT NOT NULL, version TEXT NOT NULL,
 group_id TEXT NOT NULL, source_path TEXT NOT NULL, size INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', method TEXT, matching_file_id INTEGER,
 file_id INTEGER, sha256 TEXT, destination TEXT, match_evidence TEXT,
 attempts INTEGER NOT NULL DEFAULT 0,
 retry_at REAL NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL DEFAULT
CURRENT_TIMESTAMP,
 UNIQUE(remote_id,version));
CREATE INDEX IF NOT EXISTS revision_queue ON revision(group_id,status,retry_at);
CREATE INDEX IF NOT EXISTS remote_group ON remote(group_id,eligible,deleted);
CREATE TABLE IF NOT EXISTS review(
 subject TEXT PRIMARY KEY, reason TEXT NOT NULL, fingerprint TEXT NOT NULL,
 lifecycle INTEGER NOT NULL DEFAULT 1, resolved INTEGER NOT NULL DEFAULT 0,
 delivered TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS digest(
 id INTEGER PRIMARY KEY, message_id TEXT NOT NULL UNIQUE, members TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', error TEXT);
CREATE TABLE IF NOT EXISTS run(
 id INTEGER PRIMARY KEY, started TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 finished TEXT, outcome TEXT, summary TEXT);
"""


class State:
    def __init__(self, catalog: Path, source: str):
        if source != "brendan":
            raise UsageError("This importer currently supports the source `brendan`.")
        if not catalog.is_file():
            raise UsageError("The catalog does not exist. Specify --catalog.")
        self.directory = catalog.parent / "imports"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.path = self.directory / "brendan.sqlite3"
        self.db = sqlite3.connect(self.path, timeout=30)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if self.get("schema_version", 1) != 1:
            raise UsageError("This import journal requires a different app version.")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(revision)")}
        if "match_evidence" not in columns:
            self.db.execute("ALTER TABLE revision ADD COLUMN match_evidence TEXT")
        self.set("schema_version", 1)
        if self.get("catalog") not in (None, str(catalog)):
            raise UsageError("This import journal belongs to another catalog.")
        self.set("catalog", str(catalog))
        self.db.commit()

    def get(self, key: str, default=None):
        row = self.db.execute(
            "SELECT value FROM setting WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        self.db.execute(
            ("INSERT OR REPLACE INTO setting VALUES(?,?)"), (key, json.dumps(value))
        )

    def review(self, subject: str, reason: str) -> None:
        import hashlib

        fingerprint = hashlib.sha256(reason.encode()).hexdigest()
        self.db.execute(
            """
INSERT INTO review(subject,reason,fingerprint) VALUES(?,?,?)
            ON CONFLICT(subject) DO UPDATE SET reason=excluded.reason,
            fingerprint=excluded.fingerprint,lifecycle=review.lifecycle+review.resolved,
            resolved=0,updated_at=CURRENT_TIMESTAMP""",
            (subject, reason, fingerprint),
        )
        self.db.commit()

    def resolve(self, subject: str) -> None:
        self.db.execute(("UPDATE review SET resolved=1 WHERE subject=?"), (subject,))
        self.db.commit()

    def failure(self, identity: int, reason: str) -> None:
        import time

        row = self.db.execute(
            ("SELECT attempts,source_path FROM revision WHERE id=?"), (identity,)
        ).fetchone()
        attempts = row[0] + 1
        self.db.execute(
            ("UPDATE revision SET attempts=?,retry_at=?,error=? WHERE id=?"),
            (
                attempts,
                time.time() + (300, 1800, 7200)[min(attempts - 1, 2)],
                reason,
                identity,
            ),
        )
        self.db.commit()
        if attempts >= 3:
            self.review(
                f"transfer:{identity}",
                f"{row[1]}: {reason} "
                "Check source access and destination; the importer will retry.",
            )

    def close(self) -> None:
        self.db.close()


@contextmanager
def job_lock(state: State):
    with (state.directory / "brendan.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UsageError(
                "Another Brendan importer is running for this catalog."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
