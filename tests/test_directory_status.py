from pathlib import Path
from typing import Any, cast

from sqlmodel import select

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.directory_status import (
    list_directory_entries as _list_directory_entries,
)
from rpg_librarian_mcp.mcp.directory_status import (
    summarize_directories as _summarize_directories,
)
from rpg_librarian_mcp.model import Entry, Product

FAKE_SHA = "a" * 64

JsonDict = dict[str, Any]


def list_directory_entries(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _list_directory_entries(*args, **kwargs))


def summarize_directories(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _summarize_directories(*args, **kwargs))


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _make_product(session) -> Product:
    product = Product(
        title="Core Rulebook",
        description="A book",
        artists="Someone",
        publisher="Someone Inc",
        year="2020",
    )
    session.add(product)
    session.flush()
    return product


def _make_entry(
    session,
    parent_path: str,
    filename: str,
    product=None,
) -> Entry:
    entry = Entry(
        parent_path=Path(parent_path),
        filename=filename,
        sha256=FAKE_SHA,
        size_in_bytes=10,
        mime_type="text/plain",
        media_type="text",
        product_id=product.id if product is not None else None,
    )
    session.add(entry)
    session.flush()
    return entry


def _write_file(tmp_path: Path, relative: str, content: str = "x") -> Path:
    file_path = tmp_path / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def test_list_directory_entries_non_recursive_reports_product_status(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    _write_file(tmp_path, "shelf/box/scan.txt")
    with session_scope(catalog) as session:
        product = _make_product(session)
        _make_entry(session, "shelf/box", "book.txt", product=product)
        _make_entry(session, "shelf/box", "scan.txt")
        session.commit()

    result = list_directory_entries(catalog, tmp_path / "shelf" / "box")

    assert result["path"] == "shelf/box"
    assert result["count"] == 2
    assert result["with_product"] == 1
    assert result["without_product"] == 1
    files_by_name = {f["filename"]: f for f in result["files"]}
    assert files_by_name["book.txt"]["has_product"] is True
    assert files_by_name["book.txt"]["cataloged"] is True
    assert files_by_name["scan.txt"]["has_product"] is False


def test_list_directory_entries_surfaces_uncataloged_files(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/never_scanned.txt")

    result = list_directory_entries(catalog, tmp_path / "shelf" / "box")

    assert result["count"] == 1
    assert result["files"][0]["cataloged"] is False
    assert result["files"][0]["has_product"] is False
    assert result["files"][0]["media_type"] is None


def test_list_directory_entries_non_recursive_shallow_path_does_not_crash(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/file.txt")

    result = list_directory_entries(catalog, tmp_path / "shelf", recursive=False)

    assert result["path"] == "shelf"
    assert result["count"] == 1
    assert result["files"][0]["cataloged"] is False


def test_list_directory_entries_recursive_walks_subdirectories(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box-a/book.txt")
    _write_file(tmp_path, "shelf/box-b/book.txt")

    result = list_directory_entries(catalog, tmp_path / "shelf", recursive=True)

    assert result["count"] == 2


def test_summarize_directories_sorts_by_without_product_descending(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        product = _make_product(session)
        _make_entry(session, "shelf/tidy", "book.txt", product=product)
        _make_entry(session, "shelf/messy", "a.txt")
        _make_entry(session, "shelf/messy", "b.txt")
        _make_entry(session, "shelf/messy", "c.txt")
        session.commit()

    result = summarize_directories(catalog, tmp_path)

    paths = [row["path"] for row in result["directories"]]
    assert paths[0] == "shelf/messy"
    messy_row = result["directories"][0]
    assert messy_row["with_product"] == 0
    assert messy_row["without_product"] == 3
    assert messy_row["scanned"] is True


def test_summarize_directories_include_complete_false_drops_finished_dirs(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        product = _make_product(session)
        _make_entry(session, "shelf/tidy", "book.txt", product=product)
        session.commit()

    result = summarize_directories(catalog, tmp_path, include_complete=False)

    assert result["directories"] == []


def test_summarize_directories_include_complete_true_keeps_finished_dirs(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        product = _make_product(session)
        _make_entry(session, "shelf/tidy", "book.txt", product=product)
        session.commit()

    result = summarize_directories(catalog, tmp_path, include_complete=True)

    assert [row["path"] for row in result["directories"]] == ["shelf/tidy"]


def test_summarize_directories_surfaces_never_scanned_directory(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/untouched/book.txt")

    result = summarize_directories(catalog, tmp_path)

    rows = {row["path"]: row for row in result["directories"]}
    assert "shelf/untouched" in rows
    assert rows["shelf/untouched"]["scanned"] is False
    assert rows["shelf/untouched"]["with_product"] == 0
    assert rows["shelf/untouched"]["without_product"] == 0


def test_summarize_directories_limit_and_truncated(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        for i in range(5):
            _make_entry(session, f"shelf/box{i}", "book.txt")
        session.commit()

    result = summarize_directories(catalog, tmp_path, limit=2)

    assert len(result["directories"]) == 2
    assert result["total_directories"] == 5
    assert result["truncated"] is True


def test_summarize_directories_does_not_mutate_catalog(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    summarize_directories(catalog, tmp_path)

    with session_scope(catalog) as session:
        assert len(session.exec(select(Entry)).all()) == 1
