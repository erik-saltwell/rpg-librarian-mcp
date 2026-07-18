from __future__ import annotations

import pytest

from rpg_librarian_mcp import db
from rpg_librarian_mcp.purge_errors import purge_errors
from rpg_librarian_mcp.sync import sync_catalog


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connection = db.connect()
    yield connection
    connection.close()


def _insert_entry(conn, entry_id: str, filepath: str, errors: str) -> None:
    conn.execute(
        """INSERT INTO entries (id, filepath, filename, size_in_bytes, sha256, media_type, errors)
           VALUES (?, ?, ?, 10, 'h', 'pdf', ?)""",
        (entry_id, filepath, filepath, errors),
    )


def test_removes_only_entries_with_errors(conn):
    _insert_entry(conn, "e1", "bad.pdf", '["extraction failed: boom"]')
    _insert_entry(conn, "e2", "good.pdf", "[]")
    conn.execute("INSERT INTO pdf_metadata (entry_id, page_count) VALUES ('e1', 1)")
    conn.execute("INSERT INTO pdf_metadata (entry_id, page_count) VALUES ('e2', 1)")
    conn.execute("INSERT INTO entry_text (entry_id, content) VALUES ('e1', 'partial text')")
    conn.commit()

    stats = purge_errors(conn)

    assert stats.removed == 1
    assert stats.removed_filepaths == ["bad.pdf"]
    remaining = {row["id"] for row in conn.execute("SELECT id FROM entries")}
    assert remaining == {"e2"}
    assert conn.execute("SELECT 1 FROM pdf_metadata WHERE entry_id = 'e1'").fetchone() is None
    assert conn.execute("SELECT 1 FROM entry_text WHERE entry_id = 'e1'").fetchone() is None
    assert conn.execute("SELECT 1 FROM pdf_metadata WHERE entry_id = 'e2'").fetchone() is not None


def test_no_errored_entries_is_a_no_op(conn):
    _insert_entry(conn, "e1", "fine.pdf", "[]")
    conn.commit()

    stats = purge_errors(conn)

    assert stats.removed == 0
    assert conn.execute("SELECT 1 FROM entries WHERE id = 'e1'").fetchone() is not None


def test_purged_file_is_reprocessed_as_new_on_next_sync(tmp_path, conn, monkeypatch):
    import fitz

    doc = fitz.open()
    doc.new_page()
    doc.save(tmp_path / "book.pdf")
    doc.close()

    sync_catalog(conn, tmp_path)
    conn.execute("UPDATE entries SET errors = '[\"simulated stale failure\"]' WHERE filename = 'book.pdf'")
    conn.commit()

    stats = purge_errors(conn)
    assert stats.removed == 1

    resync_stats = sync_catalog(conn, tmp_path)
    assert resync_stats.added == 1
