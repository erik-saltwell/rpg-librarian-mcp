from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, NamedTuple

from fastmcp import Context
from sqlmodel import Session

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry, Error
from ..model.ProcessingStage import ProcessingStage
from ..tools.entry_queries import entries_by_parent, entries_under, entry_by_exact_path
from .CommandProtocol import CommandProtocol
from .ProcessingError import ProcessingError


class UpdateResult(NamedTuple):
    scanned: int
    skipped: int
    succeeded: int
    errored: int
    errors: list[ProcessingError]  # capped to max_errors


class UpdateBaseCommand(CommandProtocol, ABC):
    """Shared behavior for commands that enrich already-cataloged entries.

    Unlike `UpdateCatalogCommand` (which walks the filesystem to build the
    catalog itself), subclasses here iterate `Entry` rows already in the
    catalog and write rows keyed on `entry_id` -- they assume
    `update_catalog` has already run for the files in scope.
    """

    #: Exception types that abort the whole run instead of being recorded as
    #: a per-entry error -- for failures unlikely to resolve on the next
    #: entry (e.g. bad credentials, exhausted rate limit), where catching
    #: and continuing would just produce N identical per-entry errors.
    fatal_exceptions: ClassVar[tuple[type[BaseException], ...]] = ()

    def __init__(
        self,
        catalog: Catalog,
        processing_stage: ProcessingStage,
        max_errors: int = 50,
    ) -> None:
        self.catalog = catalog
        self.processing_stage = processing_stage
        self.max_errors = max_errors

    def in_scope(self, entry: Entry) -> bool:
        """Whether `entry`'s type is one this command ever processes.

        Unlike `should_process`, this is a hard type filter, not a staleness
        check -- it applies even when `force=True`, so e.g. `read_pdfs`
        never attempts to open a non-PDF file just because `force` was
        passed. Defaults to true (no type restriction); override for
        commands that only handle a subset of media types.
        """
        return True

    @abstractmethod
    def should_process(self, session: Session, entry: Entry) -> bool:
        """Whether `entry`'s existing result (if any) is stale or missing."""
        ...

    @abstractmethod
    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        """Extract/persist this entry's result via `session.add`/`session.merge`.

        Raise on failure. Do not commit or roll back -- the base owns the
        transaction boundary. Exception: if part of the result is genuinely
        independent of a later fallible step (e.g. `ReadPdfsCommand`'s
        non-LLM signal vs. its LLM judgment call), commit that part early so
        it survives the base's rollback when the later step raises.
        """
        ...

    def _resolve_entries(
        self, session: Session, starting_path: Path, process_recursively: bool
    ) -> list[Entry]:
        absolute_path = self.catalog.to_absolute(
            self.catalog.to_relative(starting_path)
        )

        relative_path = self.catalog.to_relative(absolute_path)

        if absolute_path.is_file():
            entry = entry_by_exact_path(
                session, relative_path.parent, relative_path.name
            )
            if entry is None:
                raise ValueError(
                    f"{starting_path} is not cataloged -- run update_catalog first"
                )
            return [entry]

        if not absolute_path.exists():
            raise ValueError(f"{starting_path} does not exist")

        return (
            entries_under(session, relative_path)
            if process_recursively
            else entries_by_parent(session, relative_path)
        )

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

        error_row = session.get(Error, (entry.id, self.processing_stage))
        if error_row is None:
            error_row = Error(
                entry_id=entry.id,
                stage=self.processing_stage,
                error_text=str(exc),
            )
        else:
            error_row.error_text = str(exc)
        session.add(error_row)

    def _clear_stale_error(self, session: Session, entry: Entry) -> None:
        stale_error = session.get(Error, (entry.id, self.processing_stage))
        if stale_error is not None:
            session.delete(stale_error)

    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        ctx: Context,
    ) -> UpdateResult:
        scanned = skipped = succeeded = errored = 0
        errors: list[ProcessingError] = []
        last_reported_percent = -1

        with session_scope(self.catalog) as session:
            candidates = self._resolve_entries(
                session, starting_path, process_recursively
            )
            total = len(candidates)

            for index, entry in enumerate(candidates):
                scanned += 1
                entry_relative_path = entry.path

                if not self.in_scope(entry) or (
                    not force and not self.should_process(session, entry)
                ):
                    skipped += 1
                else:
                    file_path = self.catalog.to_absolute(entry_relative_path)
                    try:
                        self.process_one(session, file_path, entry)
                    except self.fatal_exceptions:
                        session.rollback()
                        raise
                    except Exception as exc:
                        session.rollback()
                        errored += 1
                        self._record_error(
                            session, entry, entry_relative_path, exc, errors
                        )
                        session.commit()
                    else:
                        succeeded += 1
                        self._clear_stale_error(session, entry)
                        session.commit()

                percent = (index + 1) * 100 // total if total else 100
                if percent != last_reported_percent:
                    await ctx.report_progress(
                        index + 1, total, f"Scanned {index + 1}/{total}"
                    )
                last_reported_percent = percent

        return UpdateResult(
            scanned=scanned,
            skipped=skipped,
            succeeded=succeeded,
            errored=errored,
            errors=errors,
        )
