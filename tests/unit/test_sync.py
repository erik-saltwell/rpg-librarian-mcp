from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest
import trimesh
from PIL import Image

from rpg_librarian_mcp import db
from rpg_librarian_mcp.sync import sync_catalog


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connection = db.connect()
    yield tmp_path, connection
    connection.close()


def _write_pdf(path: Path, text: str = "Hello world, this is extractable PDF text.") -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def _write_image(path: Path) -> None:
    Image.new("RGBA", (20, 10), (255, 0, 0, 128)).save(path)


def _write_audio(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)  # 1 second of silence


def _write_svg(path: Path) -> None:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" '
        'viewBox="0 0 100 50"><rect width="100" height="50"/></svg>',
        encoding="utf-8",
    )


def _write_mesh(path: Path) -> None:
    trimesh.creation.box(extents=(10, 20, 30)).export(path)


def test_bootstrap_on_empty_library(library):
    root, conn = library
    stats = sync_catalog(conn, root)
    assert (root / ".catalog" / "text_fragments").is_dir()
    assert (stats.added, stats.updated, stats.unchanged, stats.removed, stats.errored) == (0, 0, 0, 0, 0)


def test_adds_one_file_per_media_type(library):
    root, conn = library
    _write_pdf(root / "book.pdf")
    _write_image(root / "cover.png")
    _write_audio(root / "track.wav")
    _write_svg(root / "map.svg")
    _write_mesh(root / "mini.stl")

    stats = sync_catalog(conn, root)
    assert stats.added == 5
    assert stats.errored == 0

    rows = {row["filename"]: dict(row) for row in conn.execute("SELECT * FROM entries")}
    assert rows["book.pdf"]["media_type"] == "pdf"
    assert rows["cover.png"]["media_type"] == "image"
    assert rows["track.wav"]["media_type"] == "audio"
    assert rows["map.svg"]["media_type"] == "vector"
    assert rows["mini.stl"]["media_type"] == "mesh"

    pdf_meta = conn.execute(
        "SELECT * FROM pdf_metadata WHERE entry_id = ?", (rows["book.pdf"]["id"],)
    ).fetchone()
    assert pdf_meta["page_count"] == 1
    assert pdf_meta["has_extractable_text"] == 1

    image_meta = conn.execute(
        "SELECT * FROM image_metadata WHERE entry_id = ?", (rows["cover.png"]["id"],)
    ).fetchone()
    assert (image_meta["width"], image_meta["height"]) == (20, 10)

    audio_meta = conn.execute(
        "SELECT * FROM audio_metadata WHERE entry_id = ?", (rows["track.wav"]["id"],)
    ).fetchone()
    assert audio_meta["duration"] > 0

    svg_meta = conn.execute(
        "SELECT * FROM svg_metadata WHERE entry_id = ?", (rows["map.svg"]["id"],)
    ).fetchone()
    assert svg_meta["width"] == 100.0

    mesh_meta = conn.execute(
        "SELECT * FROM mesh_metadata WHERE entry_id = ?", (rows["mini.stl"]["id"],)
    ).fetchone()
    assert mesh_meta["bounding_box_x_mm"] == 10.0


def test_second_call_reports_unchanged_and_skips_rehash(library, monkeypatch):
    root, conn = library
    _write_pdf(root / "book.pdf")
    sync_catalog(conn, root)

    import rpg_librarian_mcp.sync as sync_module

    calls = []
    original_hash = sync_module._hash_file

    def spy_hash(path):
        calls.append(path)
        return original_hash(path)

    monkeypatch.setattr(sync_module, "_hash_file", spy_hash)

    stats = sync_catalog(conn, root)
    assert (stats.added, stats.updated, stats.unchanged) == (0, 0, 1)
    assert calls == []


def test_changed_file_is_reextracted(library):
    root, conn = library
    pdf_path = root / "book.pdf"
    _write_pdf(pdf_path, text="Original text")
    sync_catalog(conn, root)
    original_sha = conn.execute("SELECT sha256 FROM entries WHERE filename = 'book.pdf'").fetchone()[0]

    _write_pdf(pdf_path, text="Changed text, much longer than before to change the hash")
    os.utime(pdf_path, (pdf_path.stat().st_mtime + 5, pdf_path.stat().st_mtime + 5))

    stats = sync_catalog(conn, root)
    assert (stats.added, stats.updated, stats.unchanged) == (0, 1, 0)
    new_sha = conn.execute("SELECT sha256 FROM entries WHERE filename = 'book.pdf'").fetchone()[0]
    assert new_sha != original_sha


def test_fields_not_owned_by_sync_survive_an_update(library):
    root, conn = library
    pdf_path = root / "book.pdf"
    _write_pdf(pdf_path)
    sync_catalog(conn, root)

    conn.execute("INSERT INTO products (id, folder, no_match, errors) VALUES ('p1', '.', 0, '[]')")
    conn.execute("UPDATE entries SET product_id = 'p1', isbn = '9781234567890' WHERE filename = 'book.pdf'")
    conn.commit()

    _write_pdf(pdf_path, text="Changed enough to alter the hash and trigger reprocessing")
    os.utime(pdf_path, (pdf_path.stat().st_mtime + 5, pdf_path.stat().st_mtime + 5))
    stats = sync_catalog(conn, root)
    assert stats.updated == 1

    row = conn.execute("SELECT product_id, isbn FROM entries WHERE filename = 'book.pdf'").fetchone()
    assert (row["product_id"], row["isbn"]) == ("p1", "9781234567890")


def test_deleted_file_is_removed_with_cascade(library):
    root, conn = library
    pdf_path = root / "book.pdf"
    _write_pdf(pdf_path)
    sync_catalog(conn, root)
    entry_id = conn.execute("SELECT id FROM entries WHERE filename = 'book.pdf'").fetchone()[0]

    pdf_path.unlink()
    stats = sync_catalog(conn, root)

    assert stats.removed == 1
    assert conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM pdf_metadata WHERE entry_id = ?", (entry_id,)).fetchone() is None


def test_excluded_files_and_dotdirs_are_skipped(library):
    root, conn = library
    (root / "CLAUDE.md").write_text("excluded")
    (root / "Agents.MD").write_text("excluded")
    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "secret.pdf").write_text("also excluded")
    _write_pdf(root / "book.pdf")

    stats = sync_catalog(conn, root)
    assert stats.added == 1
    filenames = {row["filename"] for row in conn.execute("SELECT filename FROM entries")}
    assert filenames == {"book.pdf"}


def test_corrupt_file_is_isolated_but_still_gets_a_base_entry(library):
    root, conn = library
    (root / "corrupt.pdf").write_bytes(b"%PDF-1.4\n" + b"\x00\x01garbage, not a real pdf" * 5)
    _write_pdf(root / "good.pdf")

    stats = sync_catalog(conn, root)
    assert stats.added == 2
    assert stats.errored == 1
    assert any("corrupt.pdf" in detail for detail in stats.error_details)

    row = conn.execute("SELECT id, media_type, sha256 FROM entries WHERE filename = 'corrupt.pdf'").fetchone()
    assert row["media_type"] == "pdf"
    assert row["sha256"]
    assert conn.execute("SELECT 1 FROM pdf_metadata WHERE entry_id = ?", (row["id"],)).fetchone() is not None
