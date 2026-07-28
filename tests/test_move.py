from pathlib import Path

import pytest
from sqlmodel import select

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.move import move
from rpg_librarian_mcp.model import Entry

FAKE_SHA = "a" * 64


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _make_entry(session, parent_path: str, filename: str) -> Entry:
    entry = Entry(
        parent_path=Path(parent_path),
        filename=filename,
        sha256=FAKE_SHA,
        size_in_bytes=10,
        mime_type="text/plain",
        media_type="text",
    )
    session.add(entry)
    session.flush()
    return entry


def _write_file(tmp_path: Path, relative: str, content: str = "x") -> Path:
    file_path = tmp_path / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def test_move_file_updates_disk_and_catalog(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = move(
        catalog,
        tmp_path / "shelf" / "box" / "book.txt",
        tmp_path / "shelf" / "new" / "renamed.txt",
    )

    assert result == {
        "source": "shelf/box/book.txt",
        "destination": "shelf/new/renamed.txt",
        "kind": "file",
        "entries_updated": 1,
    }
    assert not (tmp_path / "shelf" / "box" / "book.txt").exists()
    assert (tmp_path / "shelf" / "new" / "renamed.txt").exists()
    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert len(entries) == 1
        assert entries[0].parent_path == Path("shelf/new")
        assert entries[0].filename == "renamed.txt"


def test_move_file_with_no_catalog_entry_still_moves_on_disk(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/uncataloged.txt")

    result = move(
        catalog,
        tmp_path / "shelf" / "box" / "uncataloged.txt",
        tmp_path / "shelf" / "new" / "uncataloged.txt",
    )

    assert result["entries_updated"] == 0
    assert (tmp_path / "shelf" / "new" / "uncataloged.txt").exists()


def test_move_folder_rewrites_all_matching_entries(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/old/box/book.txt")
    _write_file(tmp_path, "shelf/old/scan.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/old/box", "book.txt")
        _make_entry(session, "shelf/old", "scan.txt")
        session.commit()

    result = move(catalog, tmp_path / "shelf" / "old", tmp_path / "shelf" / "new")

    assert result["kind"] == "folder"
    assert result["entries_updated"] == 2
    assert not (tmp_path / "shelf" / "old").exists()
    assert (tmp_path / "shelf" / "new" / "box" / "book.txt").exists()
    assert (tmp_path / "shelf" / "new" / "scan.txt").exists()
    with session_scope(catalog) as session:
        parent_paths = {e.parent_path for e in session.exec(select(Entry)).all()}
        assert parent_paths == {Path("shelf/new/box"), Path("shelf/new")}


def test_move_rejects_when_destination_already_exists(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    _write_file(tmp_path, "shelf/other/book.txt")

    with pytest.raises(ValueError, match="already exists"):
        move(
            catalog,
            tmp_path / "shelf" / "box" / "book.txt",
            tmp_path / "shelf" / "other" / "book.txt",
        )


def test_move_rejects_stale_catalog_entry_at_destination_file(tmp_path):
    """Destination has no file on disk, but a leftover Entry row already lives there."""
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/new", "book.txt")  # no matching file on disk
        session.commit()

    with pytest.raises(ValueError, match="already has a cataloged entry"):
        move(
            catalog,
            tmp_path / "shelf" / "box" / "book.txt",
            tmp_path / "shelf" / "new" / "book.txt",
        )

    assert (tmp_path / "shelf" / "box" / "book.txt").exists()
    with session_scope(catalog) as session:
        assert len(session.exec(select(Entry)).all()) == 1


def test_move_rejects_stale_catalog_entry_at_destination_folder(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/new/sub", "book.txt")  # no matching folder on disk
        session.commit()

    with pytest.raises(ValueError, match="already has cataloged entries"):
        move(catalog, tmp_path / "shelf" / "box", tmp_path / "shelf" / "new")

    assert (tmp_path / "shelf" / "box" / "book.txt").exists()


def test_move_rejects_when_source_does_not_exist(tmp_path):
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        move(
            catalog, tmp_path / "shelf" / "missing.txt", tmp_path / "shelf" / "dest.txt"
        )


def test_move_creates_missing_intermediate_destination_directories(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")

    move(
        catalog,
        tmp_path / "shelf" / "box" / "book.txt",
        tmp_path / "brand" / "new" / "category" / "book.txt",
    )

    assert (tmp_path / "brand" / "new" / "category" / "book.txt").exists()


def test_move_rejects_folder_to_top_level_destination(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")

    with pytest.raises(ValueError, match="too shallow"):
        move(catalog, tmp_path / "shelf" / "box", tmp_path / "toplevel")

    assert (tmp_path / "shelf" / "box" / "book.txt").exists()


def test_move_rejects_file_to_top_level_destination(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")

    with pytest.raises(ValueError, match="too shallow"):
        move(catalog, tmp_path / "shelf" / "box" / "book.txt", tmp_path / "book.txt")

    assert (tmp_path / "shelf" / "box" / "book.txt").exists()


def test_move_failed_rename_leaves_catalog_unchanged(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    def _boom(self, target):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "rename", _boom)

    with pytest.raises(OSError, match="simulated rename failure"):
        move(
            catalog,
            tmp_path / "shelf" / "box" / "book.txt",
            tmp_path / "shelf" / "new" / "book.txt",
        )

    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert len(entries) == 1
        assert entries[0].parent_path == Path("shelf/box")
        assert entries[0].filename == "book.txt"


def test_move_folder_survives_unrelated_bad_media_type(poisoned_catalog, tmp_path):
    """Bug 1: an out-of-scope row with an invalid media_type must not crash
    a folder move that has nothing to do with it (collision check and
    rename-loop scan both scoped elsewhere)."""
    catalog = poisoned_catalog
    _write_file(tmp_path, "shelf/old/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/old", "book.txt")
        session.commit()

    result = move(catalog, tmp_path / "shelf" / "old", tmp_path / "shelf" / "new")

    assert result["entries_updated"] == 1
    assert (tmp_path / "shelf" / "new" / "book.txt").exists()
