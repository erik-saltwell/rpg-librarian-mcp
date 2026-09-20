"""`enrich`: gather candidate evidence for files already in the catalog.

Every source writes one row per file: the query used, the results, and when they
were fetched. A query that finds nothing still writes a row, so the file is not
asked again. A failure writes an `error` row and no evidence row, so it is retried
on the next run. A source that becomes unusable (bad key, exhausted quota) stops for
the rest of the run instead of failing every remaining file.

Evidence is candidate signal for the LLM session, never an asserted identification.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import exists
from sqlmodel import Session, col, select

from ..db import session_scope
from ..enrichment.base import FatalSourceError, Source
from ..enrichment.queries import FileContext
from ..enrichment.registry import SOURCES
from ..error_rows import clear_error, record_error
from ..errors import UsageError
from ..model import (
    Disposition,
    EvidenceBase,
    File,
    FileLlmExtraction,
    FileMetadata,
    FileText,
    Root,
)
from ..model.core import FileMetadataBase
from ..observability import FileTracker, log_call_fields, log_file_fields
from ..progress import track


@dataclass
class SourceStats:
    attempted: int = 0
    with_results: int = 0
    empty: int = 0
    errors: int = 0
    skipped_reason: str | None = None
    stopped_reason: str | None = None


def _eligible(session: Session, source: Source, force: bool) -> list[FileContext]:
    """Files a source has not yet covered, as contexts, in catalog order."""
    roots = {r.id: r.path for r in session.exec(select(Root)).all()}
    statement = (
        select(File, FileMetadata, FileText)
        .join(FileMetadata, col(FileMetadata.file_id) == col(File.id), isouter=True)
        .join(FileText, col(FileText.file_id) == col(File.id), isouter=True)
        .where(col(File.missing_since).is_(None))
        .where(col(File.disposition) != Disposition.duplicate)
        .order_by(col(File.id))
    )
    if not force:
        statement = statement.where(
            ~exists().where(col(source.table.file_id) == col(File.id))
        )

    contexts = []
    for file, metadata, text in session.exec(statement).all():
        assert file.id is not None
        contexts.append(
            FileContext(
                file_id=file.id,
                path=str(Path(roots[file.root_id]) / file.relative_path),
                relative_path=file.relative_path,
                title=metadata.title if metadata else None,
                isbn=text.isbn if text else None,
                sample_pages=(text.sample_pages or {}) if text else None,
            )
        )
    return contexts


def _has_results(row: FileMetadataBase) -> bool:
    if isinstance(row, EvidenceBase):
        return bool(row.results)
    if isinstance(row, FileLlmExtraction):
        return bool(row.description or row.possible_system)
    return True


def _run_source(
    session: Session, source: Source, args: argparse.Namespace
) -> SourceStats:
    stats = SourceStats()
    reason = source.unavailable_reason()
    if reason is not None:
        stats.skipped_reason = reason
        return stats

    contexts = [c for c in _eligible(session, source, args.force) if source.wants(c)]
    if args.limit is not None:
        contexts = contexts[: args.limit]

    with track(f"enrich {source.name}", len(contexts)) as progress:
        for index, context in enumerate(contexts, start=1):
            stats.attempted += 1
            try:
                with FileTracker(context.file_id, Path(context.path)):
                    log_file_fields(source=source.name)
                    row = source.fetch(context)
            except FatalSourceError as error:
                record_error(session, context.file_id, source.stage, error)
                session.commit()
                stats.stopped_reason = str(error)
                break
            except Exception as error:
                record_error(session, context.file_id, source.stage, error)
                stats.errors += 1
            else:
                if row is not None:
                    row.file_id = context.file_id
                    session.merge(row)
                    clear_error(session, context.file_id, source.stage)
                    if _has_results(row):
                        stats.with_results += 1
                    else:
                        stats.empty += 1
            session.commit()  # one file, one transaction
            progress(index, context.relative_path, stats.errors)
    return stats


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Run the chosen sources (default: all) over files lacking their evidence."""
    names = args.source or list(SOURCES)
    if args.limit is not None and args.limit < 1:
        raise UsageError("--limit must be at least 1.")

    results: dict[str, SourceStats] = {}
    with session_scope(catalog_path) as session:
        for name in SOURCES:  # fixed run order, whatever order --source was given in
            if name in names:
                results[name] = _run_source(session, SOURCES[name], args)

    for name, stats in results.items():
        if stats.skipped_reason:
            print(f"{name}: skipped ({stats.skipped_reason})")
            continue
        print(
            f"{name}: {stats.attempted} attempted, {stats.with_results} with results, "
            f"{stats.empty} empty, {stats.errors} errors"
        )
        if stats.stopped_reason:
            print(f"  warning: {name} stopped early: {stats.stopped_reason}")
    log_call_fields(sources={n: vars(s) for n, s in results.items()})
    return 0
