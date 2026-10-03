"""Entries: the identity the tools and per-item tables use, and how to reach a file's.

Every file has exactly one `file` entry. Tables describing the catalog item (evidence,
text analysis, errors, review flags) are keyed by `entry_id`; tables describing the
file's bytes (`file_text`, `file_metadata`, the media tables, `isbn_result`) keep
`file_id`. The two ids are different numbers in general, so code that looks a row up
must use the key its table is declared with: `row_key` decides that in one place.
"""

from __future__ import annotations

from sqlmodel import Session, col, select

from .model import Entry, EntryMetadataBase, EntryType, File


def keyed_by_entry(table: type) -> bool:
    """Whether a per-item table is keyed by `entry_id` (else by `file_id`)."""
    return issubclass(table, EntryMetadataBase)


def row_key(table: type, *, file_id: int, entry_id: int) -> int:
    """The primary key value of `table`'s row for this file and its entry."""
    return entry_id if keyed_by_entry(table) else file_id


def file_entry(session: Session, file_id: int) -> Entry:
    """The entry of a file. Every file has one; a missing one is a catalog error."""
    entry = session.exec(select(Entry).where(col(Entry.file_id) == file_id)).first()
    if entry is None:
        raise LookupError(f"File {file_id} has no entry.")
    return entry


def file_entry_id(session: Session, file_id: int) -> int:
    entry_id = file_entry(session, file_id).id
    assert entry_id is not None
    return entry_id


def ensure_file_entry(session: Session, file: File) -> Entry:
    """The file's entry, created if this is a new file. The file must be flushed."""
    assert file.id is not None
    entry = session.exec(select(Entry).where(col(Entry.file_id) == file.id)).first()
    if entry is None:
        entry = Entry(type=EntryType.file, file_id=file.id)
        session.add(entry)
        session.flush()
    return entry


def entries_with_files(
    session: Session, entry_ids: list[int]
) -> dict[int, tuple[Entry, File | None]]:
    """Each found entry with its file (None for an entry that is not a file)."""
    if not entry_ids:
        return {}
    rows = session.exec(
        select(Entry, File)
        .join(File, col(File.id) == col(Entry.file_id), isouter=True)
        .where(col(Entry.id).in_(entry_ids))
    ).all()
    return {entry.id: (entry, file) for entry, file in rows if entry.id is not None}


def file_entry_ids(session: Session, file_ids: list[int]) -> dict[int, int]:
    """file id -> entry id, for files that have one (every file does)."""
    if not file_ids:
        return {}
    return {
        file_id: entry_id
        for file_id, entry_id in session.exec(
            select(col(Entry.file_id), col(Entry.id)).where(
                col(Entry.file_id).in_(file_ids)
            )
        ).all()
        if file_id is not None and entry_id is not None
    }
