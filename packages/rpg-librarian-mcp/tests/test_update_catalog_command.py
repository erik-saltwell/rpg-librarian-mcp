import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

from sqlmodel import select

from conftest import FakeProgressReporter, RecordingProgressReporter
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, Error
from rpg_librarian_mcp.observability import (
    ENTRY_PROCESSING_FILENAME,
    CallTracker,
    configure_wide_event_logs,
)
from rpg_librarian_mcp.progress import McpProgressReporter

command_module = importlib.import_module(
    "rpg_librarian_mcp.commands.UpdateCatalogCommand"
)


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _entry_log_events(catalog_dir: Path) -> list[dict]:
    log_path = catalog_dir / ENTRY_PROCESSING_FILENAME
    if not log_path.exists():
        return []
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    return [event for event in events if event["event"] == "entry_processed"]


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

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

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
    await command.process(tmp_path, True, False, FakeProgressReporter())

    file_path.unlink()
    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.removed == 1
    with session_scope(catalog) as session:
        assert session.exec(select(Entry)).all() == []


async def test_process_skips_unchanged_files_on_second_pass(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.skipped == 1
    assert result.successfully_processed == 0


async def test_force_reprocesses_unchanged_files(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    result = await command.process(tmp_path, True, True, FakeProgressReporter())

    assert result.skipped == 0
    assert result.successfully_processed == 1


async def test_non_recursive_scan_ignores_subdirectories(tmp_path):
    _make_book(tmp_path)  # lives at tmp_path/shelf/box/book.txt
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)

    result = await command.process(tmp_path, False, False, FakeProgressReporter())

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
    await command.process(shelf_a, False, False, FakeProgressReporter())
    await command.process(shelf_b, False, False, FakeProgressReporter())

    result = await command.process(shelf_a, False, False, FakeProgressReporter())

    assert result.removed == 0
    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert {e.parent_path.name for e in entries} == {"box-a", "box-b"}


async def test_processing_error_on_new_file_is_persisted_via_stub_entry(
    tmp_path, monkeypatch
):
    """Bug 3: a file that fails before ever getting an Entry row must still
    get a persisted Error row (via a stub Entry), so list_errors can surface
    it -- not just report it transiently in this call's response."""
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 1
    assert result.successfully_processed == 0
    assert result.errors[0].reason == "boom"
    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert len(entries) == 1
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].entry_id == entries[0].id
        assert errors[0].error_text == "boom"


async def test_stub_entry_causes_second_unforced_scan_to_skip_not_reerror(
    tmp_path, monkeypatch
):
    """Bug 3, pinning a side effect of the stub-entry fix: once a stub Entry
    exists, the file it stands in for is no longer "new" on the next scan.
    _should_process_row compares file mtime to the stub's updated_at (just
    set to now), so an unforced rescan skips it -- the failure no longer
    reappears in every call's inline `errors`, but the persisted Error row
    (the actual point of this fix) survives untouched. A forced rescan (or
    an actual file change) still reprocesses it normally."""
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )
    await command.process(tmp_path, True, False, FakeProgressReporter())

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 0
    assert result.skipped == 1
    with session_scope(catalog) as session:
        assert len(session.exec(select(Error)).all()) == 1


async def test_processing_error_on_existing_file_is_persisted_and_then_cleared(
    tmp_path, monkeypatch
):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )
    result = await command.process(tmp_path, True, True, FakeProgressReporter())

    assert result.errored == 1
    with session_scope(catalog) as session:
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].error_text == "boom"

    monkeypatch.undo()
    result = await command.process(tmp_path, True, True, FakeProgressReporter())

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

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 2
    assert len(result.errors) == 1


async def test_deleting_a_file_cascades_to_its_error_row(tmp_path, monkeypatch):
    file_path = _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )
    await command.process(tmp_path, True, True, FakeProgressReporter())
    with session_scope(catalog) as session:
        assert len(session.exec(select(Error)).all()) == 1
    monkeypatch.undo()

    file_path.unlink()
    result = await command.process(tmp_path, True, False, FakeProgressReporter())

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

    result = await command.process(tmp_path, True, False, McpProgressReporter(ctx))

    assert result.scanned == file_count
    # 150 files compressed into <=101 distinct percentage buckets (0-100).
    assert ctx.report_progress.call_count <= 101
    assert ctx.report_progress.call_count < file_count


async def test_reporter_is_updated_once_per_scanned_file(tmp_path):
    """Unlike MCP's percentage throttling, the loop itself must call
    `update()` unconditionally for every file -- throttling is entirely the
    reporter's own policy, not the loop's."""
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    file_count = 5
    for i in range(file_count):
        (shelf / f"book{i:03d}.txt").write_text(str(i))
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)
    reporter = RecordingProgressReporter()

    result = await command.process(tmp_path, True, False, reporter)

    assert len(reporter.update_calls) == result.scanned == file_count
    assert reporter.torn_down is True


async def test_root_level_file_is_reported_as_error_not_a_crash(tmp_path):
    """Bug: a supported file placed directly in the library root (parent_path
    depth < 2) crashed the whole recursive scan with a raw ValueError from
    ParentPathType's bind-time validation, instead of being reported as a
    per-file error like `move` reports the same constraint."""
    (tmp_path / "roottest.txt").write_text("hello world")
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 1
    assert result.successfully_processed == 1
    assert "roottest.txt" in result.errors[0].reason
    assert "too shallow to be cataloged" in result.errors[0].reason

    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
        assert [e.filename for e in entries] == ["book.txt"]


async def test_root_level_file_single_file_call_reports_clean_error(tmp_path):
    file_path = tmp_path / "roottest.txt"
    file_path.write_text("hello world")
    catalog = _catalog(tmp_path)
    command = UpdateCatalogCommand(catalog)

    result = await command.process(file_path, False, False, FakeProgressReporter())

    assert result.errored == 1
    assert result.successfully_processed == 0
    assert "too shallow to be cataloged" in result.errors[0].reason


async def test_directory_mode_survives_unrelated_bad_media_type(poisoned_catalog):
    """Bug 1: the removal-reconciliation loop's full-table scan must not
    crash on an out-of-scope row with an invalid media_type."""
    catalog = poisoned_catalog
    shelf = catalog.library_root / "shelf" / "box"
    shelf.mkdir(parents=True)
    (shelf / "book.txt").write_text("hello world")
    command = UpdateCatalogCommand(catalog)

    result = await command.process(shelf, False, False, FakeProgressReporter())

    assert result.scanned == 1
    assert result.successfully_processed == 1
    assert result.removed == 0


async def test_directory_mode_at_root_self_heals_phantom_row(poisoned_catalog):
    """Bug 1, follow-through: a root-scoped directory-mode call includes the
    poisoned row's own directory in scope. Since media_type now degrades to
    `unknown` on read instead of raising (TolerantMediaType), the row
    deserializes fine, is recognized as having no backing file on disk, and
    gets removed by the existing reconciliation logic -- no new tool needed
    to recover from a bad row like this."""
    catalog = poisoned_catalog
    shelf = catalog.library_root / "shelf" / "box"
    shelf.mkdir(parents=True)
    (shelf / "book.txt").write_text("hello world")
    command = UpdateCatalogCommand(catalog)

    result = await command.process(
        catalog.library_root, True, False, FakeProgressReporter()
    )

    assert result.removed == 1
    with session_scope(catalog) as session:
        remaining = {e.filename for e in session.exec(select(Entry)).all()}
        assert remaining == {"book.txt"}


async def test_new_file_emits_started_and_success_entry_log_lines(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)

    await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert [event["outcome"] for event in events] == ["started", "success"]
    for event in events:
        assert event["entry_path"] == "shelf/box/book.txt"
        assert event["command"] == "UpdateCatalogCommand"


async def test_success_entry_log_line_breaks_down_hash_vs_db_time(tmp_path):
    """The success line reports `compute_ms` (hashing/mime-sniffing) and
    `db_write_ms` (add/flush/commit) as separate fields -- so a slow
    `update-catalog` run can be attributed to file hashing vs. database
    round trips instead of just an opaque total duration."""
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)

    await command.process(tmp_path, True, False, FakeProgressReporter())

    success_event = next(
        event
        for event in _entry_log_events(catalog.catalog_dir)
        if event["outcome"] == "success"
    )
    assert isinstance(success_event["existing_lookup_ms"], float)
    assert isinstance(success_event["compute_ms"], float)
    assert isinstance(success_event["db_write_ms"], float)


async def test_error_entry_log_line_still_reports_compute_and_db_time(
    tmp_path, monkeypatch
):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )

    await command.process(tmp_path, True, False, FakeProgressReporter())

    error_event = next(
        event
        for event in _entry_log_events(catalog.catalog_dir)
        if event["outcome"] == "error"
    )
    assert isinstance(error_event["compute_ms"], float)
    assert isinstance(error_event["db_write_ms"], float)


async def test_skipped_entry_log_line_reports_the_existing_lookup_time(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    await command.process(tmp_path, True, False, FakeProgressReporter())

    skipped_event = next(
        event
        for event in _entry_log_events(catalog.catalog_dir)
        if event["outcome"] == "skipped"
    )
    assert isinstance(skipped_event["existing_lookup_ms"], float)


async def test_skipped_file_emits_a_lightweight_entry_log_line(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.skipped == 1
    events = _entry_log_events(catalog.catalog_dir)
    skipped_events = [event for event in events if event["outcome"] == "skipped"]
    assert len(skipped_events) == 1
    assert "duration_ms" not in skipped_events[0]


async def test_compute_failure_emits_an_error_entry_log_line(tmp_path, monkeypatch):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)
    monkeypatch.setattr(
        command_module,
        "generate_sha256",
        lambda path: (_ for _ in ()).throw(ValueError("boom")),
    )

    await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert [event["outcome"] for event in events] == ["started", "error"]
    error_event = events[1]
    assert error_event["error_type"] == "ValueError"
    assert error_event["error_message"] == "boom"
    assert "traceback" not in error_event


async def test_too_shallow_path_emits_an_entry_log_error_with_no_entry_id(tmp_path):
    (tmp_path / "roottest.txt").write_text("hello world")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)

    await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert len(events) == 1
    assert events[0]["outcome"] == "error"
    assert events[0]["entry_id"] is None
    assert "too shallow" in events[0]["error_message"]
    assert "duration_ms" not in events[0]


async def test_entry_log_lines_carry_the_enclosing_call_ids_call_id(tmp_path):
    _make_book(tmp_path)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)

    with CallTracker("update_catalog", transport="cli") as tracker:
        await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert all(event["call_id"] == tracker.call_id for event in events)


async def test_fatal_style_failure_still_reports_partial_counts_on_the_command_event(
    tmp_path, monkeypatch
):
    """Even though `UpdateCatalogCommand` has no `fatal_exceptions` concept of
    its own, the per-file counts are still updated incrementally (not just
    once at the end), so a bug that aborted the loop early would still leave
    the command-level event showing accurate partial counts rather than
    zeros."""
    for name in ("a", "b"):
        d = tmp_path / "shelf" / name
        d.mkdir(parents=True)
        (d / "book.txt").write_text(name)
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = UpdateCatalogCommand(catalog)

    with CallTracker("update_catalog", transport="cli") as tracker:
        await command.process(tmp_path, True, False, FakeProgressReporter())

    assert tracker.event_fields["scanned"] == 2
    assert tracker.event_fields["successfully_processed"] == 2
