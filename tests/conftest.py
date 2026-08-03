import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import ensure_bootstrapped
from rpg_librarian_mcp.progress import ProgressUpdate


class FakeProgressReporter:
    """A no-op `ProgressReporter` for tests that don't care about progress
    reporting -- stands in wherever a test previously passed a bare
    `AsyncMock()` as `ctx`."""

    @asynccontextmanager
    async def track(self, total: int) -> AsyncIterator[ProgressUpdate]:
        async def update(current: int, filename: str, errors: int) -> None:
            pass

        yield update


class RecordingProgressReporter:
    """A `ProgressReporter` that records every `update()` call and whether
    `track()`'s context manager tore down -- including when the caller's
    `with` block exits via an uncaught exception (e.g. a fatal exception
    re-raised out of `UpdateBaseCommand.process`'s loop)."""

    def __init__(self) -> None:
        self.update_calls: list[tuple[int, str, int]] = []
        self.torn_down = False

    @asynccontextmanager
    async def track(self, total: int) -> AsyncIterator[ProgressUpdate]:
        async def update(current: int, filename: str, errors: int) -> None:
            self.update_calls.append((current, filename, errors))

        try:
            yield update
        finally:
            self.torn_down = True


@pytest.fixture(autouse=True)
def _isolate_from_ambient_database_url(monkeypatch):
    """Tests must not be affected by a dev-only DATABASE_URL in the repo's .env.

    An empty (but present) value stops env.py's `if database_url:` check from
    firing, and blocks python-dotenv's override=False load from re-populating
    it from any .env found while walking up from a tmp_path under the repo.
    """
    monkeypatch.setenv("DATABASE_URL", "")


def insert_raw_entry(
    catalog: Catalog,
    parent_path: str,
    filename: str,
    media_type: str,
    sha256: str = "f" * 64,
    size_in_bytes: int = 1,
    mime_type: str = "application/octet-stream",
) -> None:
    """Plant an Entry row via raw SQL, bypassing Pydantic/enum validation.

    Reproduces a row like production's "canary.pdf" (`media_type="document"`,
    not a valid MediaType member) -- the ORM would reject that value at
    construction time, so the only way to get such a row into the table (as
    happened in production) is a direct SQL insert.
    """
    ensure_bootstrapped(catalog)
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    conn = sqlite3.connect(catalog.db_path)
    try:
        conn.execute(
            "INSERT INTO entry "
            "(id, created_at, updated_at, parent_path, filename, sha256, "
            "size_in_bytes, mime_type, media_type, product_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                uuid.uuid4().hex,
                now,
                now,
                parent_path,
                filename,
                sha256,
                size_in_bytes,
                mime_type,
                media_type,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def poisoned_catalog(tmp_path: Path) -> Catalog:
    """A catalog with one unrelated entry whose media_type is not a valid enum member.

    Mirrors production's canary.pdf: parent_path="." (library root itself),
    a file that does not exist on disk, media_type="document" (never a valid
    MediaType member). Any operation scoped to a *different* subtree must not
    be affected by this row.
    """
    catalog = Catalog(library_root=tmp_path)
    insert_raw_entry(
        catalog,
        parent_path=".",
        filename="canary.pdf",
        media_type="document",
        mime_type="application/pdf",
    )
    return catalog
