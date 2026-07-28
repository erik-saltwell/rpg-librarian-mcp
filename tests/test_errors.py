import importlib
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.errors import list_errors as _list_errors
from rpg_librarian_mcp.model import Entry, Error
from rpg_librarian_mcp.model.Error import ErrorStage

command_module = importlib.import_module(
    "rpg_librarian_mcp.commands.UpdateCatalogCommand"
)

FAKE_SHA = "a" * 64

JsonDict = dict[str, Any]


def list_errors(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _list_errors(*args, **kwargs))


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


def test_list_errors_returns_all_errors_with_path(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "broken.txt")
        session.add(
            Error(
                entry_id=entry.id,
                stage=ErrorStage.populate_file_data,
                error_text="boom",
            )
        )
        session.commit()

    result = list_errors(catalog)

    assert result["count"] == 1
    assert result["errors"][0]["path"] == "shelf/box/broken.txt"
    assert result["errors"][0]["stage"] == "populate_file_data"
    assert result["errors"][0]["error_text"] == "boom"
    assert isinstance(result["errors"][0]["occurred_at"], str)


def test_list_errors_filters_by_path_subtree(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        entry_a = _make_entry(session, "shelf/box-a", "broken.txt")
        entry_b = _make_entry(session, "shelf/box-b", "broken.txt")
        session.add(
            Error(
                entry_id=entry_a.id, stage=ErrorStage.populate_file_data, error_text="a"
            )
        )
        session.add(
            Error(
                entry_id=entry_b.id, stage=ErrorStage.populate_file_data, error_text="b"
            )
        )
        session.commit()

    result = list_errors(catalog, path=tmp_path / "shelf" / "box-a")

    assert result["count"] == 1
    assert result["errors"][0]["path"] == "shelf/box-a/broken.txt"


def test_list_errors_filters_by_stage(tmp_path):
    # ErrorStage has only one member today, so this can't test *exclusion* of
    # a non-matching stage -- only that passing the filter still matches.
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "broken.txt")
        session.add(
            Error(
                entry_id=entry.id,
                stage=ErrorStage.populate_file_data,
                error_text="boom",
            )
        )
        session.commit()

    matching = list_errors(catalog, stage=ErrorStage.populate_file_data)

    assert matching["count"] == 1


async def test_list_errors_surfaces_a_permission_failure_on_a_brand_new_file(
    tmp_path, monkeypatch
):
    """Bug 3, through the reported symptom: update_catalog's inline response
    already showed this error; the bug was that list_errors() afterward
    returned {"errors":[],"count":0} because no Entry existed yet to attach
    an Error row to. This runs the real command (not a hand-built Error
    row) and checks list_errors actually finds it."""
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    (shelf / "book.txt").write_text("hello world")
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(PermissionError("denied")),
    )

    await command.process(shelf, False, False, AsyncMock())

    result = list_errors(catalog)

    assert result["count"] == 1
    assert result["errors"][0]["path"] == "shelf/box/book.txt"
    assert "denied" in result["errors"][0]["error_text"]


def test_list_errors_empty_when_no_errors(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "fine.txt")
        session.commit()

    result = list_errors(catalog)

    assert result == {"errors": [], "count": 0}
