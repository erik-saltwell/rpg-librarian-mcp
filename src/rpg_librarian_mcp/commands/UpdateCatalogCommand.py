from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, TypedDict

from fastmcp import Context
from sqlmodel import Session, select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry, Error
from ..model.Error import ErrorStage
from ..model.MediaType import MediaType
from ..tools.entry_queries import entries_by_parent, entries_under
from ..tools.media_type import detect_media_type, detect_mime_type
from ..tools.path_helper import walk_filesystem
from ..tools.sha256 import generate_file_size, generate_sha256
from .ProcessingError import ProcessingError


class EntryFields(TypedDict):
    sha256: str
    size_in_bytes: int
    mime_type: str
    media_type: MediaType


def _compute_entry_fields(path: Path) -> EntryFields:
    mime_type = detect_mime_type(path)
    media_type = detect_media_type(mime_type, path.suffix)
    return EntryFields(
        sha256=generate_sha256(path),
        size_in_bytes=generate_file_size(path),
        mime_type=mime_type,
        media_type=media_type,
    )


def _should_process_row(file_path: Path, existing: Entry | None, force: bool) -> bool:
    if force:
        return True
    if existing is None:
        return True
    file_time: datetime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
    return file_time > existing.updated_at


def _clear_stale_error(session: Session, entry: Entry) -> None:
    stale_error = session.get(Error, (entry.id, ErrorStage.populate_file_data))
    if stale_error is not None:
        session.delete(stale_error)


def _create_stub_entry(session: Session, parent_path: Path, filename: str) -> Entry:
    """A placeholder Entry for a file that has never processed successfully.

    error.entry_id is NOT NULL with a FK to entry.id, so an Error can't be
    persisted without one. This stub gives a failing-on-first-scan file an
    id to attach an Error to; a later successful process overwrites its
    placeholder fields the same way it would for any other existing entry.
    """
    stub = Entry(
        parent_path=parent_path,
        filename=filename,
        sha256="0" * 64,
        size_in_bytes=0,
        mime_type="application/octet-stream",
        media_type=MediaType.unknown,
    )
    session.add(stub)
    session.flush()
    return stub


class UpdateCatalogResult(NamedTuple):
    scanned: int
    skipped: int
    successfully_processed: int
    removed: int
    errored: int
    errors: list[ProcessingError]  # capped to max_errors


class UpdateCatalogCommand:
    def __init__(self, catalog: Catalog, max_errors: int = 50) -> None:
        self.catalog = catalog
        self.max_errors = max_errors

    def _record_error(
        self,
        session: Session,
        entry: Entry,
        entry_relative_path: Path,
        exc: Exception,
        errors: list[ProcessingError],
    ) -> None:
        if len(errors) < self.max_errors:
            errors.append(ProcessingError(path=entry_relative_path, reason=str(exc)))

        error_row = session.get(Error, (entry.id, ErrorStage.populate_file_data))
        if error_row is None:
            error_row = Error(
                entry_id=entry.id,
                stage=ErrorStage.populate_file_data,
                error_text=str(exc),
            )
        else:
            error_row.error_text = str(exc)
        session.add(error_row)

    async def process(
        self, starting_path: Path, process_recursively: bool, force: bool, ctx: Context
    ) -> UpdateCatalogResult:
        relative_path = self.catalog.to_relative(starting_path)
        absolute_path = self.catalog.to_absolute(relative_path)
        candidates = list(walk_filesystem(absolute_path, process_recursively))
        paths_on_disk: set[Path] = set()
        total = len(candidates)
        scanned = skipped = successfully_processed = errored = 0
        errors: list[ProcessingError] = []
        last_reported_percent = -1

        with session_scope(self.catalog) as session:
            for index, file_path in enumerate(candidates):
                scanned += 1
                entry_relative_path = self.catalog.to_relative(file_path)
                paths_on_disk.add(entry_relative_path)
                parent_path = entry_relative_path.parent
                filename = entry_relative_path.name

                existing = session.exec(
                    select(Entry).where(
                        Entry.parent_path == parent_path,
                        Entry.filename == filename,
                    )
                ).first()

                should_process = _should_process_row(file_path, existing, force)

                if not should_process:
                    skipped += 1
                else:
                    try:
                        fields = _compute_entry_fields(file_path)
                    except Exception as exc:
                        errored += 1
                        error_target = existing or _create_stub_entry(
                            session, parent_path, filename
                        )
                        self._record_error(
                            session, error_target, entry_relative_path, exc, errors
                        )
                    else:
                        successfully_processed += 1
                        if existing is None:
                            entry = Entry(
                                parent_path=parent_path, filename=filename, **fields
                            )
                        else:
                            for key, value in fields.items():
                                setattr(existing, key, value)
                            entry = existing
                        session.add(entry)
                        session.flush()
                        _clear_stale_error(session, entry)

                    session.commit()  # Stage 6 — per file, not batched

                percent = (index + 1) * 100 // total if total else 100
                if percent != last_reported_percent:
                    await ctx.report_progress(
                        index + 1, total, f"Scanned {index + 1}/{total}"
                    )

                last_reported_percent = percent
            removed = 0
            if absolute_path.is_dir():
                in_scope_entries = (
                    entries_under(session, relative_path)
                    if process_recursively
                    else entries_by_parent(session, relative_path)
                )
                for entry in in_scope_entries:
                    if entry.path not in paths_on_disk:
                        session.delete(entry)
                        removed += 1
                session.commit()
        return UpdateCatalogResult(
            scanned=scanned,
            skipped=skipped,
            successfully_processed=successfully_processed,
            removed=removed,
            errored=errored,
            errors=errors,
        )
