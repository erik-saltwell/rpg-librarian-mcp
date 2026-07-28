import importlib
from pathlib import Path
from unittest.mock import AsyncMock

from sqlmodel import select

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, Error

command_module = importlib.import_module(
    "rpg_librarian_mcp.commands.UpdateCatalogCommand"
)


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _make_book(tmp_path: Path) -> Path:
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    file_path = shelf / "book.txt"
    file_path.write_text("hello world")
    return file_path


async def test_process_creates_entries_for_new_files(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.scanned == 1
    assert result.successfully_processed == 1
    assert result.errored == 0
    assert result.errors == []

    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert [e.filename for e in entries] == ["book.txt"]


async def test_process_removes_entries_for_deleted_files(tmp_path):
    file_path = _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, AsyncMock())

    file_path.unlink()
    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.removed == 1
    with session_scope(catalog) as session:
        assert session.exec(select(Entry)).all() == []


async def test_process_skips_unchanged_files_on_second_pass(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, AsyncMock())

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.skipped == 1
    assert result.successfully_processed == 0


async def test_force_reprocesses_unchanged_files(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, AsyncMock())

    result = await command.process(tmp_path, True, True, AsyncMock())

    assert result.skipped == 0
    assert result.successfully_processed == 1


async def test_non_recursive_scan_ignores_subdirectories(tmp_path):
    _make_book(tmp_path)  # lives at tmp_path/shelf/box/book.txt
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)

    result = await command.process(tmp_path, False, False, AsyncMock())

    assert result.scanned == 0
    with session_scope(catalog) as session:
        assert session.exec(select(Entry)).all() == []


async def test_non_recursive_deletion_does_not_touch_sibling_folder(tmp_path):
    shelf_a = tmp_path / "shelf" / "box-a"
    shelf_a.mkdir(parents=True)
    (shelf_a / "book.txt").write_text("a")
    shelf_b = tmp_path / "shelf" / "box-b"
    shelf_b.mkdir(parents=True)
    (shelf_b / "book.txt").write_text("b")
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(shelf_a, False, False, AsyncMock())
    await command.process(shelf_b, False, False, AsyncMock())

    result = await command.process(shelf_a, False, False, AsyncMock())

    assert result.removed == 0
    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert {e.parent_path.name for e in entries} == {"box-a", "box-b"}


async def test_processing_error_on_new_file_is_reported_but_not_persisted(
    tmp_path, monkeypatch
):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.errored == 1
    assert result.errors[0].reason == "boom"
    with session_scope(catalog) as session:
        assert session.exec(select(Entry)).all() == []
        assert session.exec(select(Error)).all() == []


async def test_processing_error_on_existing_file_is_persisted_and_then_cleared(
    tmp_path, monkeypatch
):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, AsyncMock())

    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )
    result = await command.process(tmp_path, True, True, AsyncMock())

    assert result.errored == 1
    with session_scope(catalog) as session:
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].error_text == "boom"

    monkeypatch.undo()
    result = await command.process(tmp_path, True, True, AsyncMock())

    assert result.successfully_processed == 1
    with session_scope(catalog) as session:
        assert session.exec(select(Error)).all() == []


async def test_max_errors_caps_reported_errors_but_not_the_count(tmp_path, monkeypatch):
    for name in ("a", "b"):
        d = tmp_path / "shelf" / name
        d.mkdir(parents=True)
        (d / "book.txt").write_text(name)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog, max_errors=1)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.errored == 2
    assert len(result.errors) == 1


async def test_deleting_a_file_cascades_to_its_error_row(tmp_path, monkeypatch):
    file_path = _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, AsyncMock())
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )
    await command.process(tmp_path, True, True, AsyncMock())
    with session_scope(catalog) as session:
        assert len(session.exec(select(Error)).all()) == 1
    monkeypatch.undo()

    file_path.unlink()
    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.removed == 1
    with session_scope(catalog) as session:
        assert session.exec(select(Entry)).all() == []
        assert session.exec(select(Error)).all() == []


async def test_progress_reporting_is_throttled_by_percentage(tmp_path):
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    file_count = 150
    for i in range(file_count):
        (shelf / f"book{i:03d}.txt").write_text(str(i))
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    ctx = AsyncMock()

    result = await command.process(tmp_path, True, False, ctx)

    assert result.scanned == file_count
    # 150 files compressed into <=101 distinct percentage buckets (0-100).
    assert ctx.report_progress.call_count <= 101
    assert ctx.report_progress.call_count < file_count
