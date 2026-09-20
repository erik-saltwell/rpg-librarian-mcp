from pathlib import Path
from typing import Any, cast

import pytest
from sqlmodel import select

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.directory_status import (
    list_directory_entries as _list_directory_entries,
)
from rpg_librarian_mcp.mcp.directory_status import (
    summarize_directories as _summarize_directories,
)
from rpg_librarian_mcp.model import Entry, IdentificationMethod, Product

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
        identification_method=IdentificationMethod.manual,
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


def test_list_directory_entries_recursive_distinguishes_same_named_files_by_path(
    tmp_path,
):
    """Bug: recursive listings only returned each file's bare `filename`, so
    same-named files in different subdirectories (e.g. two scans both named
    `book.txt`) were indistinguishable in the response."""
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box-a/book.txt")
    _write_file(tmp_path, "shelf/box-b/book.txt")

    result = list_directory_entries(catalog, tmp_path / "shelf", recursive=True)

    paths = {f["path"] for f in result["files"]}
    assert paths == {"shelf/box-a/book.txt", "shelf/box-b/book.txt"}


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


def test_summarize_directories_rejects_zero_limit(tmp_path):
    """Bug 2: limit=0 silently clamped to 1 rather than being rejected."""
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="positive"):
        summarize_directories(catalog, tmp_path, limit=0)


def test_summarize_directories_rejects_negative_limit(tmp_path):
    """Bug 2: limit=-1 silently clamped to 1 rather than being rejected."""
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="positive"):
        summarize_directories(catalog, tmp_path, limit=-1)


def test_summarize_directories_does_not_mutate_catalog(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    summarize_directories(catalog, tmp_path)

    with session_scope(catalog) as session:
        assert len(session.exec(select(Entry)).all()) == 1


def test_list_directory_entries_recursive_survives_unrelated_bad_media_type(
    poisoned_catalog, tmp_path
):
    """Bug 1: an out-of-scope row with an invalid media_type must not crash
    a query scoped to a different subtree."""
    catalog = poisoned_catalog
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = list_directory_entries(catalog, tmp_path / "shelf", recursive=True)

    assert result["count"] == 1
    assert result["files"][0]["filename"] == "book.txt"


def test_summarize_directories_survives_unrelated_bad_media_type(
    poisoned_catalog, tmp_path
):
    """Bug 1: same, for summarize_directories's grouped-count query."""
    catalog = poisoned_catalog
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = summarize_directories(catalog, tmp_path / "shelf")

    assert [row["path"] for row in result["directories"]] == ["shelf/box"]


def test_list_directory_entries_survives_bad_media_type_at_library_root(
    poisoned_catalog, tmp_path
):
    """Bug 1: the poisoned row itself lives at the library root (parent_path
    "."), so a root-scoped call -- the primary way summarize_directories and
    recursive list_directory_entries get used -- must not crash either."""
    catalog = poisoned_catalog
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = list_directory_entries(catalog, tmp_path, recursive=True)

    assert result["count"] == 1
    assert result["files"][0]["filename"] == "book.txt"


def test_list_directory_entries_on_file_path_reports_catalog_state(tmp_path):
    """Bug: a file `path` was looked up via entries_by_parent(file_path),
    which never matches -- the entry lives under the file's *parent*
    directory. Result was a phantom uncataloged entry for a cataloged file."""
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        product = _make_product(session)
        _make_entry(session, "shelf/box", "book.txt", product=product)
        session.commit()

    result = list_directory_entries(catalog, tmp_path / "shelf" / "box" / "book.txt")

    assert result["count"] == 1
    assert result["files"][0]["cataloged"] is True
    assert result["files"][0]["has_product"] is True
    assert result["files"][0]["media_type"] == "text"


def test_list_directory_entries_recursive_on_file_path_reports_catalog_state(
    tmp_path,
):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = list_directory_entries(
        catalog, tmp_path / "shelf" / "box" / "book.txt", recursive=True
    )

    assert result["count"] == 1
    assert result["files"][0]["cataloged"] is True


def test_summarize_directories_rejects_nonexistent_path(tmp_path):
    """Bug: a nonexistent path returned an empty-but-successful result,
    indistinguishable from a real directory with no scanned subdirectories,
    instead of erroring like update_catalog/list_directory_entries do."""
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        summarize_directories(catalog, tmp_path / "nonexistent_xyz")


def test_summarize_directories_rejects_file_path(tmp_path):
    """Bug: a file `path` was silently treated as a fabricated, always-empty
    directory row instead of erroring."""
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.txt")

    with pytest.raises(ValueError, match="not a directory"):
        summarize_directories(catalog, tmp_path / "shelf" / "box" / "book.txt")


def test_summarize_directories_survives_bad_media_type_at_library_root(
    poisoned_catalog, tmp_path
):
    """Bug 1: same, scoped at the library root itself.

    The poisoned row's own parent_path is "." -- a depth-<2 path a real
    Entry could never have (ParentPathType rejects it on any normal bind).
    Such a group must not surface as a phantom directory row; only the
    legitimate "shelf/box" group should appear.
    """
    catalog = poisoned_catalog
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = summarize_directories(catalog, tmp_path)

    assert {row["path"] for row in result["directories"]} == {"shelf/box"}
