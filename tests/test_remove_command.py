from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from conftest import insert_raw_entry
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.RemoveCommand import RemoveCommand
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


async def _catalog_file(tmp_path: Path, parent: str, filename: str, text: str) -> Path:
    shelf = tmp_path / parent
    shelf.mkdir(parents=True, exist_ok=True)
    file_path = shelf / filename
    file_path.write_text(text)
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(tmp_path, True, False, AsyncMock())
    return file_path


def _entry_exists(catalog: Catalog, filename: str) -> bool:
    with session_scope(catalog) as session:
        return (
            session.exec(select(Entry).where(Entry.filename == filename)).first()
            is not None
        )


async def test_removes_a_single_file_moving_it_to_trash_and_dropping_the_entry(
    tmp_path,
):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    command = RemoveCommand(catalog)

    result = await command.process(file_path, False, False, AsyncMock())

    assert result.succeeded == 1
    assert not file_path.exists()
    trashed = catalog.catalog_dir / "trash" / "shelf" / "box" / "book.pdf"
    assert trashed.exists()
    assert trashed.read_text() == "hello"
    assert _entry_exists(catalog, "book.pdf") is False


async def test_removes_every_entry_recursively_under_a_directory(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "one.pdf", "a")
    await _catalog_file(tmp_path, "shelf/box/sub", "two.pdf", "b")
    catalog = _catalog(tmp_path)
    command = RemoveCommand(catalog)

    result = await command.process(tmp_path / "shelf" / "box", True, False, AsyncMock())

    assert result.succeeded == 2
    assert (catalog.catalog_dir / "trash" / "shelf" / "box" / "one.pdf").exists()
    assert (
        catalog.catalog_dir / "trash" / "shelf" / "box" / "sub" / "two.pdf"
    ).exists()
    assert _entry_exists(catalog, "one.pdf") is False
    assert _entry_exists(catalog, "two.pdf") is False


async def test_recursive_removal_prunes_emptied_directories(tmp_path):
    """Bug: process_one only moved files -- a recursive remove left
    `shelf/box/` and `shelf/box/sub/` behind as empty directories, which
    summarize_directories then surfaces forever as phantom
    never-scanned rows."""
    await _catalog_file(tmp_path, "shelf/box", "one.pdf", "a")
    await _catalog_file(tmp_path, "shelf/box/sub", "two.pdf", "b")
    catalog = _catalog(tmp_path)
    command = RemoveCommand(catalog)

    await command.process(tmp_path / "shelf" / "box", True, False, AsyncMock())

    assert not (tmp_path / "shelf" / "box").exists()
    assert (tmp_path / "shelf").exists()


async def test_pruning_does_not_touch_an_unrelated_empty_sibling_directory(tmp_path):
    """Pruning is scoped to directories this run actually removed a file
    from -- an incidentally-empty sibling folder the run never touched
    must be left alone, not swept up as collateral cleanup."""
    await _catalog_file(tmp_path, "shelf/box", "one.pdf", "a")
    (tmp_path / "shelf" / "untouched-empty").mkdir(parents=True)
    catalog = _catalog(tmp_path)
    command = RemoveCommand(catalog)

    await command.process(tmp_path / "shelf" / "box", True, False, AsyncMock())

    assert not (tmp_path / "shelf" / "box").exists()
    assert (tmp_path / "shelf" / "untouched-empty").exists()


async def test_non_recursive_leaves_files_in_subdirectories_untouched(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "one.pdf", "a")
    await _catalog_file(tmp_path, "shelf/box/sub", "two.pdf", "b")
    catalog = _catalog(tmp_path)
    command = RemoveCommand(catalog)

    result = await command.process(
        tmp_path / "shelf" / "box", False, False, AsyncMock()
    )

    assert result.succeeded == 1
    assert _entry_exists(catalog, "one.pdf") is False
    assert _entry_exists(catalog, "two.pdf") is True
    assert (tmp_path / "shelf" / "box" / "sub" / "two.pdf").exists()
    assert (tmp_path / "shelf" / "box").exists()


async def test_rejects_a_trash_collision_and_leaves_the_file_and_entry_in_place(
    tmp_path,
):
    """Bug-shaped scenario: removing, restoring, then removing the same
    path again must not silently overwrite the earlier trashed copy."""
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    trash_path = catalog.catalog_dir / "trash" / "shelf" / "box" / "book.pdf"
    trash_path.parent.mkdir(parents=True, exist_ok=True)
    trash_path.write_text("already trashed content")
    command = RemoveCommand(catalog)

    result = await command.process(file_path, False, False, AsyncMock())

    assert result.errored == 1
    assert result.succeeded == 0
    assert file_path.exists()
    assert _entry_exists(catalog, "book.pdf") is True
    assert trash_path.read_text() == "already trashed content"


async def test_process_one_rejects_a_corrupt_parent_path_that_would_escape_trash(
    tmp_path,
):
    """A row planted by raw SQL (bypassing ParentPathType's bind validation
    -- see conftest.insert_raw_entry / the poisoned_catalog fixture) could
    carry a traversal parent_path. process_one must refuse to move such an
    entry rather than resolving a path outside .catalog/trash/ and
    following it with Path.rename."""
    catalog = _catalog(tmp_path)
    insert_raw_entry(
        catalog,
        parent_path="../../etc",
        filename="passwd",
        media_type="text",
        mime_type="text/plain",
    )
    with session_scope(catalog) as session:
        entry = session.exec(select(Entry).where(Entry.filename == "passwd")).one()
        command = RemoveCommand(catalog)

        with pytest.raises(ValueError, match="corrupt parent_path"):
            command.process_one(session, tmp_path / "irrelevant.txt", entry)


async def test_should_process_is_always_true(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        entry = session.exec(select(Entry).where(Entry.filename == "book.pdf")).one()
        command = RemoveCommand(catalog)
        assert command.should_process(session, entry) is True
    assert file_path.exists()


async def test_second_run_on_the_same_file_path_errors_since_nothing_is_left_there(
    tmp_path,
):
    """The file physically moved away, so a second `remove` on the same
    path has neither a file nor an Entry left to resolve -- same "does not
    exist" error every other path-taking tool gives for a missing path."""
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    command = RemoveCommand(catalog)
    await command.process(file_path, False, False, AsyncMock())

    with pytest.raises(ValueError, match="does not exist"):
        await command.process(file_path, False, False, AsyncMock())
