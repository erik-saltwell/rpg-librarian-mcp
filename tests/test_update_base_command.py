import json
from pathlib import Path
from typing import ClassVar

import pytest
from sqlmodel import Session, select

from conftest import FakeProgressReporter, RecordingProgressReporter
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.UpdateBaseCommand import UpdateBaseCommand
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, Error, FileMetadata, ProcessingStage
from rpg_librarian_mcp.observability import (
    ENTRY_PROCESSING_FILENAME,
    CallTracker,
    configure_wide_event_logs,
    log_entry_fields,
)


class FakeUpdateCommand(UpdateBaseCommand):
    """Minimal subclass exercising UpdateBaseCommand's shared machinery.

    `process_one` writes a FileMetadata row (reusing a real table so the
    generic session.merge/commit/rollback plumbing has something concrete to
    act on) and raises for any filename listed in `fail_filenames`.
    """

    def __init__(
        self,
        catalog: Catalog,
        max_errors: int = 50,
        fail_filenames: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(catalog, ProcessingStage.extract_metadata, max_errors)
        self.fail_filenames = fail_filenames
        self.processed: list[str] = []

    def should_process(self, session: Session, entry: Entry) -> bool:
        return session.get(FileMetadata, entry.id) is None

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        self.processed.append(entry.filename)
        if entry.filename in self.fail_filenames:
            raise ValueError(f"boom:{entry.filename}")
        session.merge(FileMetadata(entry_id=entry.id, title="processed"))


class FakeFatalUpdateCommand(FakeUpdateCommand):
    """`FakeUpdateCommand`, but a failure in `fail_filenames` aborts the
    whole run instead of being recorded as a per-entry error."""

    fatal_exceptions: ClassVar[tuple[type[BaseException], ...]] = (ValueError,)


class FakeInstrumentedUpdateCommand(FakeUpdateCommand):
    """`FakeUpdateCommand`, but `process_one` also reports a business-context
    field via `log_entry_fields`, the way a real command reports e.g. which
    external APIs it called."""

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        log_entry_fields(matched_source="google_books")
        super().process_one(session, file_path, entry)


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _entry_log_events(catalog_dir: Path) -> list[dict]:
    log_path = catalog_dir / ENTRY_PROCESSING_FILENAME
    if not log_path.exists():
        return []
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    return [event for event in events if event["event"] == "entry_processed"]


async def _catalog_file(tmp_path: Path, parent: str, filename: str, text: str) -> Path:
    """Write a file to disk and run UpdateCatalogCommand so it gets a real Entry."""
    shelf = tmp_path / parent
    shelf.mkdir(parents=True, exist_ok=True)
    file_path = shelf / filename
    file_path.write_text(text)
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(
        tmp_path, True, False, FakeProgressReporter()
    )
    return file_path


async def test_raises_for_a_single_file_never_cataloged(tmp_path):
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    file_path = shelf / "book.txt"
    file_path.write_text("hello")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)

    with pytest.raises(ValueError, match="not cataloged"):
        await command.process(file_path, False, False, FakeProgressReporter())


async def test_raises_for_a_directory_that_does_not_exist(tmp_path):
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)

    with pytest.raises(ValueError, match="does not exist"):
        await command.process(
            tmp_path / "nowhere", False, False, FakeProgressReporter()
        )


async def test_empty_directory_scope_is_not_an_error(tmp_path):
    empty_dir = tmp_path / "shelf" / "empty"
    empty_dir.mkdir(parents=True)
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)

    result = await command.process(empty_dir, False, False, FakeProgressReporter())

    assert result.scanned == 0
    assert result.errors == []


async def test_process_one_succeeds_and_persists_its_result(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.scanned == 1
    assert result.succeeded == 1
    assert result.errored == 0
    with session_scope(catalog) as session:
        rows = session.exec(select(FileMetadata)).all()
        assert [r.title for r in rows] == ["processed"]


async def test_should_process_false_causes_a_skip_on_the_second_pass(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.skipped == 1
    assert result.succeeded == 0
    assert command.processed == ["book.txt"]  # not called again on the skip


async def test_force_bypasses_should_process(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    result = await command.process(tmp_path, True, True, FakeProgressReporter())

    assert result.succeeded == 1
    assert result.skipped == 0
    assert command.processed == ["book.txt", "book.txt"]


async def test_error_is_recorded_with_this_commands_processing_stage(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog, fail_filenames=frozenset({"book.txt"}))

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 1
    assert result.succeeded == 0
    assert result.errors[0].reason == "boom:book.txt"
    with session_scope(catalog) as session:
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].stage == ProcessingStage.extract_metadata
        assert errors[0].error_text == "boom:book.txt"
        assert session.exec(select(FileMetadata)).all() == []


async def test_error_is_cleared_after_a_subsequent_successful_reprocess(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    failing_command = FakeUpdateCommand(catalog, fail_filenames=frozenset({"book.txt"}))
    await failing_command.process(tmp_path, True, False, FakeProgressReporter())
    with session_scope(catalog) as session:
        assert len(session.exec(select(Error)).all()) == 1

    fixed_command = FakeUpdateCommand(catalog)
    result = await fixed_command.process(tmp_path, True, True, FakeProgressReporter())

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        assert session.exec(select(Error)).all() == []


async def test_max_errors_caps_reported_errors_but_not_the_count(tmp_path):
    await _catalog_file(tmp_path, "shelf/a", "one.txt", "a")
    await _catalog_file(tmp_path, "shelf/b", "two.txt", "b")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(
        catalog, max_errors=1, fail_filenames=frozenset({"one.txt", "two.txt"})
    )

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 2
    assert len(result.errors) == 1


async def test_non_recursive_scope_ignores_subdirectories(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)

    result = await command.process(tmp_path, False, False, FakeProgressReporter())

    assert result.scanned == 0


async def test_single_cataloged_file_processes_only_that_entry(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    await _catalog_file(tmp_path, "shelf/box2", "other.txt", "world")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)

    result = await command.process(file_path, False, False, FakeProgressReporter())

    assert result.scanned == 1
    assert command.processed == ["book.txt"]


async def test_reporter_is_updated_once_per_scanned_entry_skipped_or_processed(
    tmp_path,
):
    """The CLI backend needs an update on every entry, skipped or processed,
    not just on percentage changes -- the loop must call `update()`
    unconditionally, leaving throttling entirely to the reporter."""
    await _catalog_file(tmp_path, "shelf/a", "one.txt", "a")
    await _catalog_file(tmp_path, "shelf/b", "two.txt", "b")
    catalog = _catalog(tmp_path)
    command = FakeUpdateCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())  # skip both
    reporter = RecordingProgressReporter()

    result = await command.process(tmp_path, True, False, reporter)

    assert result.skipped == 2
    assert len(reporter.update_calls) == result.scanned == 2
    assert reporter.torn_down is True


async def test_fatal_exception_still_tears_down_the_reporter(tmp_path):
    """A fatal exception aborts `process` by re-raising through the loop --
    the reporter's `track()` context manager must still tear down (e.g. so a
    CLI `Live` display doesn't stay stuck on screen) rather than being left
    open."""
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    command = FakeFatalUpdateCommand(catalog, fail_filenames=frozenset({"book.txt"}))
    reporter = RecordingProgressReporter()

    with pytest.raises(ValueError, match=r"boom:book\.txt"):
        await command.process(tmp_path, True, False, reporter)

    assert reporter.torn_down is True


async def test_process_one_emits_started_and_success_entry_log_lines(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = FakeUpdateCommand(catalog)

    await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert [event["outcome"] for event in events] == ["started", "success"]
    for event in events:
        assert event["entry_path"] == str(file_path.relative_to(tmp_path))
        assert event["command"] == "FakeUpdateCommand"
    assert isinstance(events[1]["duration_ms"], float)


async def test_process_one_failure_emits_an_error_entry_log_line_without_a_traceback(
    tmp_path,
):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = FakeUpdateCommand(catalog, fail_filenames=frozenset({"book.txt"}))

    await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert [event["outcome"] for event in events] == ["started", "error"]
    error_event = events[1]
    assert error_event["error_type"] == "ValueError"
    assert error_event["error_message"] == "boom:book.txt"
    assert "traceback" not in error_event


async def test_skipped_entry_emits_a_lightweight_entry_log_line(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = FakeUpdateCommand(catalog)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    fresh_command = FakeUpdateCommand(catalog)
    result = await fresh_command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.skipped == 1
    events = _entry_log_events(catalog.catalog_dir)
    skipped_events = [event for event in events if event["outcome"] == "skipped"]
    assert len(skipped_events) == 1
    assert "duration_ms" not in skipped_events[0]


async def test_entry_log_lines_carry_the_enclosing_call_ids_call_id(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = FakeUpdateCommand(catalog)

    with CallTracker("update_metadata", transport="cli") as tracker:
        await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    assert all(event["call_id"] == tracker.call_id for event in events)


async def test_log_entry_fields_attaches_business_context_to_the_entry_event(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = FakeInstrumentedUpdateCommand(catalog)

    await command.process(tmp_path, True, False, FakeProgressReporter())

    events = _entry_log_events(catalog.catalog_dir)
    success_event = next(event for event in events if event["outcome"] == "success")
    assert success_event["matched_source"] == "google_books"


async def test_fatal_exception_still_reports_partial_counts_on_the_command_event(
    tmp_path,
):
    """A fatal exception aborts the run after the loop's first entry -- the
    per-command wide event (written by `CallTracker` when the exception
    propagates out of `dispatch`/the MCP middleware) should still show that
    one entry was scanned and succeeded, not zeros."""
    await _catalog_file(tmp_path, "shelf/a", "one.txt", "a")
    await _catalog_file(tmp_path, "shelf/b", "two.txt", "b")
    catalog = _catalog(tmp_path)
    configure_wide_event_logs(catalog.catalog_dir)
    command = FakeFatalUpdateCommand(catalog, fail_filenames=frozenset({"two.txt"}))

    with (
        pytest.raises(ValueError, match=r"boom:two\.txt"),
        CallTracker("update_metadata", transport="cli") as tracker,
    ):
        await command.process(tmp_path, True, False, RecordingProgressReporter())

    # Order between the two entries isn't guaranteed, so assert on the
    # relationship rather than which one died: the failing entry is
    # counted as scanned but neither succeeded nor errored (the fatal
    # exception skips that bookkeeping on its way out), while `errored`
    # only ever counts *non-fatal* per-entry failures.
    assert tracker.event_fields["errored"] == 0
    assert tracker.event_fields["scanned"] == tracker.event_fields["succeeded"] + 1
