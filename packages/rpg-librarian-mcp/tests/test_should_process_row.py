from datetime import UTC, datetime, timedelta

from rpg_librarian_mcp.commands.UpdateCatalogCommand import _should_process_row
from rpg_librarian_mcp.model import Entry


def _entry_updated_at(when: datetime) -> Entry:
    entry = Entry(
        parent_path="shelf/box",
        filename="book.txt",
        sha256="a" * 64,
        size_in_bytes=1,
        mime_type="text/plain",
        media_type="text",
    )
    entry.updated_at = when
    return entry


def test_force_always_processes_regardless_of_existing(tmp_path):
    file_path = tmp_path / "book.txt"
    file_path.write_text("x")
    future = _entry_updated_at(datetime.now(UTC) + timedelta(days=1))

    assert _should_process_row(file_path, future, force=True) is True


def test_no_existing_entry_always_processes(tmp_path):
    file_path = tmp_path / "book.txt"
    file_path.write_text("x")

    assert _should_process_row(file_path, None, force=False) is True


def test_processes_when_file_is_newer_than_existing_entry(tmp_path):
    file_path = tmp_path / "book.txt"
    file_path.write_text("x")
    stale = _entry_updated_at(datetime.now(UTC) - timedelta(days=1))

    assert _should_process_row(file_path, stale, force=False) is True


def test_skips_when_file_is_not_newer_than_existing_entry(tmp_path):
    file_path = tmp_path / "book.txt"
    file_path.write_text("x")
    fresh = _entry_updated_at(datetime.now(UTC) + timedelta(days=1))

    assert _should_process_row(file_path, fresh, force=False) is False
