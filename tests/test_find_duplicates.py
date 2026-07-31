from pathlib import Path
from typing import Any, cast

import pytest

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.find_duplicates import find_duplicates as _find_duplicates
from rpg_librarian_mcp.model import Entry, IdentificationMethod, Product

JsonDict = dict[str, Any]


def find_duplicates(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _find_duplicates(*args, **kwargs))


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _make_entry(
    session, parent_path: str, filename: str, sha256: str, product=None
) -> Entry:
    entry = Entry(
        parent_path=Path(parent_path),
        filename=filename,
        sha256=sha256,
        size_in_bytes=10,
        mime_type="text/plain",
        media_type="text",
        product_id=product.id if product is not None else None,
    )
    session.add(entry)
    session.flush()
    return entry


def test_find_duplicates_groups_entries_sharing_a_hash(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box-a", "book.txt", "a" * 64)
        _make_entry(session, "shelf/box-b", "copy.txt", "a" * 64)
        _make_entry(session, "shelf/box-c", "unique.txt", "b" * 64)
        session.commit()

    result = find_duplicates(catalog)

    assert result["duplicate_group_count"] == 1
    assert result["duplicate_file_count"] == 2
    group = result["duplicate_groups"][0]
    assert group["sha256"] == "a" * 64
    assert group["count"] == 2
    paths = {e["path"] for e in group["entries"]}
    assert paths == {"shelf/box-a/book.txt", "shelf/box-b/copy.txt"}


def test_find_duplicates_reports_has_product_per_entry(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        product = Product(
            title="Keeper Rulebook", identification_method=IdentificationMethod.manual
        )
        session.add(product)
        session.flush()
        _make_entry(session, "shelf/box-a", "book.txt", "a" * 64, product=product)
        _make_entry(session, "shelf/box-b", "copy.txt", "a" * 64)
        session.commit()

    result = find_duplicates(catalog)

    entries_by_path = {e["path"]: e for e in result["duplicate_groups"][0]["entries"]}
    assert entries_by_path["shelf/box-a/book.txt"]["has_product"] is True
    assert entries_by_path["shelf/box-b/copy.txt"]["has_product"] is False


def test_find_duplicates_sorts_groups_by_count_descending(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "a1.txt", "a" * 64)
        _make_entry(session, "shelf/box", "a2.txt", "a" * 64)
        _make_entry(session, "shelf/box", "b1.txt", "b" * 64)
        _make_entry(session, "shelf/box", "b2.txt", "b" * 64)
        _make_entry(session, "shelf/box", "b3.txt", "b" * 64)
        session.commit()

    result = find_duplicates(catalog)

    counts = [g["count"] for g in result["duplicate_groups"]]
    assert counts == [3, 2]


def test_find_duplicates_returns_empty_when_no_duplicates(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "a.txt", "a" * 64)
        _make_entry(session, "shelf/box", "b.txt", "b" * 64)
        session.commit()

    result = find_duplicates(catalog)

    assert result == {
        "duplicate_groups": [],
        "duplicate_group_count": 0,
        "duplicate_file_count": 0,
    }


def test_find_duplicates_scopes_to_a_directory_subtree(tmp_path):
    catalog = _catalog(tmp_path)
    (tmp_path / "shelf").mkdir(parents=True)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/in-scope-a", "book.txt", "a" * 64)
        _make_entry(session, "shelf/in-scope-b", "copy.txt", "a" * 64)
        _make_entry(session, "other/out-of-scope", "copy.txt", "a" * 64)
        session.commit()

    result = find_duplicates(catalog, path=tmp_path / "shelf")

    assert result["duplicate_file_count"] == 2
    paths = {e["path"] for e in result["duplicate_groups"][0]["entries"]}
    assert paths == {"shelf/in-scope-a/book.txt", "shelf/in-scope-b/copy.txt"}


def test_find_duplicates_scoped_to_the_library_root_matches_unscoped(tmp_path):
    """The library root is a depth-0 relative path ("."), unlike every
    other real scope -- confirm entries_under's is_relative_to filtering
    (no depth guard, unlike entries_by_parent/entry_by_exact_path) still
    matches every entry rather than raising or returning nothing."""
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box-a", "book.txt", "a" * 64)
        _make_entry(session, "shelf/box-b", "copy.txt", "a" * 64)
        session.commit()

    scoped = find_duplicates(catalog, path=tmp_path)
    unscoped = find_duplicates(catalog, path=None)

    assert scoped == unscoped
    assert scoped["duplicate_file_count"] == 2


def test_find_duplicates_rejects_non_existent_path(tmp_path):
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        find_duplicates(catalog, path=tmp_path / "does_not_exist")


def test_find_duplicates_rejects_a_file_path(tmp_path):
    catalog = _catalog(tmp_path)
    (tmp_path / "shelf" / "box").mkdir(parents=True)
    (tmp_path / "shelf" / "box" / "book.txt").write_text("hi")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt", "a" * 64)
        session.commit()

    with pytest.raises(ValueError, match="not a directory"):
        find_duplicates(catalog, path=tmp_path / "shelf" / "box" / "book.txt")
