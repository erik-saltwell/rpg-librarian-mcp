from __future__ import annotations

import sqlite3

import pytest

from rpg_librarian_mcp import db
from rpg_librarian_mcp.catalog_io import export_catalog, import_catalog


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connection = db.connect()
    yield connection
    connection.close()


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO products (id, folder, title, publisher, no_match, errors) "
        "VALUES ('p1', 'DriveThruRPG/Chaosium/Test', 'Test Product', 'Chaosium', 0, '[]')"
    )
    conn.execute(
        """INSERT INTO entries
           (id, filepath, filename, extension, parent_folder, grandparent_folder,
            size_in_bytes, sha256, media_type, product_id, title, isbn, errors)
           VALUES ('e1', 'DriveThruRPG/Chaosium/Test/book.pdf', 'book.pdf', '.pdf',
                   'Test', 'Chaosium', 123, 'abc123', 'pdf', 'p1', 'Book Title',
                   '9781234567890', '[]')"""
    )
    conn.execute("INSERT INTO pdf_metadata (entry_id, page_count, is_encrypted) VALUES ('e1', 42, 0)")
    conn.execute("INSERT INTO entry_text (entry_id, content) VALUES ('e1', 'goblin cave adventure')")
    conn.commit()


def test_export_round_trips_through_import(conn):
    _seed(conn)

    exported = export_catalog(conn)
    assert exported["products"][0]["title"] == "Test Product"
    assert exported["entries"][0]["media_type_metadata"]["page_count"] == 42
    assert exported["entries"][0]["media_type_metadata"]["is_encrypted"] is False
    assert exported["entries"][0]["text"] == "goblin cave adventure"

    db.ensure_schema(conn)
    conn.execute("DELETE FROM entry_text")
    conn.execute("DELETE FROM pdf_metadata")
    conn.execute("DELETE FROM entries")
    conn.execute("DELETE FROM products")
    conn.commit()

    stats = import_catalog(conn, exported)
    assert stats.products == 1
    assert stats.entries == 1

    reexported = export_catalog(conn)
    reexported.pop("exported_at")
    exported.pop("exported_at")
    assert reexported == exported


def test_import_upserts_without_touching_unrelated_rows(conn):
    _seed(conn)
    exported = export_catalog(conn)

    conn.execute(
        "INSERT INTO products (id, folder, title, no_match, errors) VALUES ('p2', 'Other', 'Other Product', 0, '[]')"
    )
    conn.commit()

    import_catalog(conn, exported)

    titles = {row["id"]: row["title"] for row in conn.execute("SELECT id, title FROM products")}
    assert titles == {"p1": "Test Product", "p2": "Other Product"}
