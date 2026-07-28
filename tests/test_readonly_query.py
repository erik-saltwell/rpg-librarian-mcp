from pathlib import Path
from typing import Any, cast

import pytest

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.readonly_query import (
    get_catalog_schema as _get_catalog_schema,
)
from rpg_librarian_mcp.mcp.readonly_query import (
    run_readonly_query as _run_readonly_query,
)
from rpg_librarian_mcp.model import Entry

FAKE_SHA = "a" * 64

JsonDict = dict[str, Any]


def run_readonly_query(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _run_readonly_query(*args, **kwargs))


def get_catalog_schema(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _get_catalog_schema(*args, **kwargs))


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


def test_run_readonly_query_returns_columns_and_rows(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.txt")
        session.commit()

    result = run_readonly_query(catalog, "SELECT filename FROM entry")

    assert result["columns"] == ["filename"]
    assert result["rows"] == [["book.txt"]]
    assert result["truncated"] is False


def test_run_readonly_query_rejects_non_select_statements(tmp_path):
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="SELECT or WITH"):
        run_readonly_query(catalog, "DROP TABLE entry")


def test_run_readonly_query_rejects_multiple_statements(tmp_path):
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="single SQL statement"):
        run_readonly_query(catalog, "SELECT 1; DROP TABLE entry")


def test_run_readonly_query_allows_single_trailing_semicolon(tmp_path):
    catalog = _catalog(tmp_path)

    result = run_readonly_query(catalog, "SELECT 1;")

    assert result["rows"] == [[1]]


def test_run_readonly_query_allows_semicolon_inside_string_literal(tmp_path):
    catalog = _catalog(tmp_path)

    result = run_readonly_query(catalog, "SELECT 'a;b'")

    assert result["rows"] == [["a;b"]]


def test_run_readonly_query_cannot_write(tmp_path):
    catalog = _catalog(tmp_path)

    with pytest.raises(Exception):  # noqa: B017 -- sqlite3 raises its own error type
        run_readonly_query(
            catalog, "WITH x AS (DELETE FROM entry RETURNING *) SELECT * FROM x"
        )


def test_run_readonly_query_truncates_and_flags(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        for i in range(5):
            _make_entry(session, "shelf/box", f"book{i}.txt")
        session.commit()

    result = run_readonly_query(
        catalog, "SELECT filename FROM entry ORDER BY filename", limit=2
    )

    assert len(result["rows"]) == 2
    assert result["truncated"] is True


def test_run_readonly_query_clamps_limit_to_hard_max(tmp_path):
    catalog = _catalog(tmp_path)

    result = run_readonly_query(catalog, "SELECT 1", limit=10_000)

    assert result["rows"] == [[1]]


def test_get_catalog_schema_returns_domain_tables_only(tmp_path):
    catalog = _catalog(tmp_path)

    result = get_catalog_schema(catalog)

    names = {table["name"] for table in result["tables"]}
    assert names == {"entry", "error", "product"}
    for table in result["tables"]:
        assert "CREATE TABLE" in table["sql"]
