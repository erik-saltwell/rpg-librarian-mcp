"""`scan`: make the catalog describe what is on the share.

Per root: walk every catalogable file, skip the unchanged ones (same size and
whole-second mtime as recorded), and for the rest copy the file local, hash it,
detect its media type, extract embedded and per-media metadata, sample PDF text and
barcodes, then delete the local copy. One share read serves every extraction.

The hash join runs after each file: a match against a row whose path has gone
missing is a *move* (the row keeps its product and disposition and just changes
location); a match against a present row makes the newer copy a `duplicate`.
Rows whose path is under the library's `.trash/` are never walked and never marked
missing, but they stay in the join, so a discarded file that reappears in a later
dump is flagged as a duplicate rather than raised as a new question.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import fitz
from sqlmodel import Session, col, select

from rpg_librarian_tools.files import MediaType, inspect_file
from rpg_librarian_tools.identifiers import IdentifierKind, find_publication_identifiers
from rpg_librarian_tools.pdf import extract_text, scan_identifiers

from ..db import session_scope
from ..error_rows import clear_error, record_error
from ..errors import UsageError
from ..infrastructure.isolated_worker import IsolatedWorkerPool, WorkerPool
from ..infrastructure.walk import walk_files
from ..metadata.extractors import generate_extractor
from ..metadata.extractors.pdf_extractor import PdfExtractor
from ..model import (
    AudioMetadata,
    Disposition,
    DtrpgResult,
    Error,
    File,
    FileMetadata,
    FileText,
    FileTextAnalysis,
    GoogleSearchResult,
    ImageMetadata,
    IsbnResult,
    MeshMetadata,
    PdfMetadata,
    ProcessingStage,
    Root,
    RootKind,
    RpggeekResult,
    VideoMetadata,
)
from ..observability import (
    FileTracker,
    log_call_fields,
    log_file_fields,
    log_file_skipped,
    mark_file_error,
)
from ..paths import TRASH_DIRNAME
from ..progress import track

# Per-file tables that `scan` owns and replaces on every (re)extraction.
_SCAN_TABLES = (
    FileMetadata,
    PdfMetadata,
    ImageMetadata,
    AudioMetadata,
    VideoMetadata,
    MeshMetadata,
    FileText,
)
# Evidence gathered by `enrich`: stale only when the file's content changed.
_EVIDENCE_TABLES = (DtrpgResult, RpggeekResult, IsbnResult, GoogleSearchResult)
_SCAN_STAGES = (ProcessingStage.scan, ProcessingStage.metadata, ProcessingStage.text)

_TEXT_SAMPLE_HEAD = 5
_TEXT_SAMPLE_TAIL = 2
_BARCODE_SAMPLE_HEAD = 2
_BARCODE_SAMPLE_TAIL = 1


def _text_pages(page_count: int) -> tuple[int, ...]:
    head = set(range(min(_TEXT_SAMPLE_HEAD, page_count)))
    tail = set(range(max(0, page_count - _TEXT_SAMPLE_TAIL), page_count))
    return tuple(sorted(head | tail))


def _barcode_pages(page_count: int) -> tuple[int, ...]:
    head = set(range(min(_BARCODE_SAMPLE_HEAD, page_count)))
    tail = set(range(max(0, page_count - _BARCODE_SAMPLE_TAIL), page_count))
    return tuple(sorted(head | tail))


def _is_trashed(relative_path: str) -> bool:
    return PurePosixPath(relative_path).parts[:1] == (TRASH_DIRNAME,)


@dataclass
class ScanStats:
    seen: int = 0
    skipped: int = 0
    processed: int = 0
    moved: int = 0
    duplicates: int = 0
    missing: int = 0
    errored: int = 0
    unreachable_roots: list[str] = field(default_factory=list)


class Scanner:
    def __init__(self, session: Session, pool: WorkerPool, force: bool) -> None:
        self.session = session
        self.pool = pool
        self.force = force
        self.stats = ScanStats()
        # The current file's temporary copy and its real path, so error text can
        # name the file on the share instead of a throwaway local path.
        self._local_copy = ""
        self._share_path = ""
        self.library_root_id: int | None = None

    # -- roots ---------------------------------------------------------------

    def collect(self, root: Root) -> list[str] | None:
        """List a root's catalogable files, or None if the root is unreachable."""
        base = Path(root.path)
        if not base.is_dir():
            self.stats.unreachable_roots.append(root.path)
            return None
        return [p.relative_to(base).as_posix() for p in walk_files(base)]

    def mark_missing(self, root: Root, seen_paths: set[str]) -> None:
        """Flag rows under a reachable root whose path has gone.

        Runs for every root *before* any file is processed, so that a file moved
        by hand (within a root or across roots) meets its old row already marked
        missing and is recognised as a move instead of a duplicate.
        """
        rows = self.session.exec(
            select(File)
            .where(col(File.root_id) == root.id)
            .where(col(File.missing_since).is_(None))
        ).all()
        now = datetime.now(UTC)
        for row in rows:
            if row.relative_path in seen_paths or _is_trashed(row.relative_path):
                continue
            row.missing_since = now
            self.session.add(row)
            self.stats.missing += 1
        self.session.commit()

    def process_root(self, root: Root, candidates: list[str]) -> None:
        base = Path(root.path)
        with (
            tempfile.TemporaryDirectory(prefix="rpg-librarian-scan-") as tmp,
            track(f"scan {root.label or base.name}", len(candidates)) as progress,
        ):
            for index, relative in enumerate(candidates, start=1):
                self._scan_one(root, base, relative, Path(tmp))
                self.session.commit()  # one file, one transaction
                progress(index, relative, self.stats.errored)
        root.last_scanned_at = datetime.now(UTC)
        self.session.add(root)
        self.session.commit()

    # -- one file ------------------------------------------------------------

    def _scan_one(self, root: Root, base: Path, relative: str, local_dir: Path) -> None:
        self.stats.seen += 1
        path = base / relative
        stat = path.stat()
        size, mtime = stat.st_size, int(stat.st_mtime)

        existing = self.session.exec(
            select(File)
            .where(col(File.root_id) == root.id)
            .where(col(File.relative_path) == relative)
        ).first()

        if existing is not None and self._can_skip(existing, size, mtime):
            existing.last_seen_at = datetime.now(UTC)
            existing.missing_since = None
            self.session.add(existing)
            self.stats.skipped += 1
            log_file_skipped(existing.id, path, action="unchanged", size_bytes=size)
            return

        with FileTracker(
            existing.id if existing else None,
            path,
            root_id=root.id,
            size_bytes=size,
            action=self._action(existing, size, mtime),
        ) as tracker:
            file = self._process(root, path, relative, size, mtime, existing, local_dir)
            tracker.file_id = file.id
            self.stats.processed += 1

    def _action(self, existing: File | None, size: int, mtime: int) -> str:
        """Why a file is being processed, for its log event."""
        if existing is None:
            return "new"
        if self.force:
            return "forced"
        if existing.size_bytes != size or existing.mtime != mtime:
            return "changed"
        return "retry"  # unchanged, but it failed last time

    def _can_skip(self, existing: File, size: int, mtime: int) -> bool:
        if self.force:
            return False
        if existing.size_bytes != size or existing.mtime != mtime:
            return False
        if existing.sha256 is None:
            return False  # never extracted successfully
        has_error = self.session.exec(
            select(Error.file_id)
            .where(col(Error.file_id) == existing.id)
            .where(col(Error.stage).in_(_SCAN_STAGES))
        ).first()
        return has_error is None

    def _process(
        self,
        root: Root,
        path: Path,
        relative: str,
        size: int,
        mtime: int,
        existing: File | None,
        local_dir: Path,
    ) -> File:
        now = datetime.now(UTC)
        local = local_dir / path.name
        self._local_copy, self._share_path = str(local), str(path)
        try:
            try:
                shutil.copyfile(path, local)
                inspection = inspect_file(local)
            except Exception as error:
                file = existing or self._new_row(root, relative, size, mtime)
                file.size_bytes, file.mtime, file.last_seen_at = size, mtime, now
                file.missing_since = None
                self.session.add(file)
                self.session.flush()
                self._record_error(file, ProcessingStage.scan, error)
                self.stats.errored += 1
                return file

            log_file_fields(
                sha256=inspection.sha256, media_type=inspection.media_type.value
            )

            if existing is None:
                moved = self._find_moved(inspection.sha256)
                if moved is not None:
                    return self._apply_move(moved, root, relative, size, mtime, now)

            file = existing or self._new_row(root, relative, size, mtime)
            content_changed = (
                file.sha256 is not None and file.sha256 != inspection.sha256
            )
            file.size_bytes, file.mtime, file.last_seen_at = size, mtime, now
            file.missing_since = None
            file.sha256 = inspection.sha256
            file.mime_type = inspection.mime_type
            file.media_type = inspection.media_type
            if content_changed:
                self._reset_judgment(file)
            self.session.add(file)
            self.session.flush()

            self._clear_errors(file)
            self._clear_scan_rows(file)
            self._extract(file, local, inspection.media_type)
            self._join_duplicates(file)
            return file
        finally:
            local.unlink(missing_ok=True)

    def _new_row(self, root: Root, relative: str, size: int, mtime: int) -> File:
        assert root.id is not None
        return File(
            root_id=root.id, relative_path=relative, size_bytes=size, mtime=mtime
        )

    def _reset_judgment(self, file: File) -> None:
        """Different content at the same path invalidates every earlier decision."""
        file.disposition = Disposition.unfiled
        file.product_id = None
        file.duplicate_of_id = None
        for table in _EVIDENCE_TABLES:
            row = self.session.get(table, file.id)
            if row is not None:
                self.session.delete(row)
        for other in self.session.exec(
            select(File).where(col(File.duplicate_of_id) == file.id)
        ).all():
            other.disposition = Disposition.unfiled
            other.duplicate_of_id = None
            self.session.add(other)

    # -- extraction ----------------------------------------------------------

    def _extract(self, file: File, local: Path, media_type: MediaType) -> None:
        assert file.id is not None
        try:
            extractor = generate_extractor(media_type, local, self.pool)
            embedded = extractor.extract_file_metadata()
            embedded.file_id = file.id
            self.session.merge(embedded)
            custom = extractor.extract_custom_metadata()
            if custom is not None:
                custom.file_id = file.id
                self.session.merge(custom)
        except Exception as error:
            self._record_error(file, ProcessingStage.metadata, error)
            self.stats.errored += 1
            return

        if media_type is MediaType.pdf:
            try:
                self._extract_pdf_text(file, local)
            except Exception as error:
                self._record_error(file, ProcessingStage.text, error)
                self.stats.errored += 1

    def _extract_pdf_text(self, file: File, local: Path) -> None:
        assert file.id is not None
        doc = fitz.open(local)
        try:
            if doc.needs_pass or doc.page_count == 0:
                return
            page_count = doc.page_count
        finally:
            doc.close()

        barcodes = self.pool.submit(scan_identifiers, local, _barcode_pages(page_count))
        barcode = barcodes[0] if barcodes else None
        extraction = self.pool.submit(extract_text, local, _text_pages(page_count))
        pages = {str(page.page + 1): page.text for page in extraction.pages}
        log_file_fields(
            page_count=page_count,
            barcode_matched=barcode is not None,
            pages_sampled=extraction.pages_sampled,
            pages_ocr=extraction.pages_ocr,
        )

        isbn = issn = None
        if barcode is not None:
            isbn = barcode.value if barcode.kind is IdentifierKind.ISBN else None
            issn = barcode.value if barcode.kind is IdentifierKind.ISSN else None
        if isbn is None and issn is None:
            found = find_publication_identifiers("\n".join(pages.values()))
            if found:
                first = found[0]
                isbn = first.value if first.kind is IdentifierKind.ISBN else None
                issn = first.value if first.kind is IdentifierKind.ISSN else None
        if isbn is None and issn is None:
            fallback = PdfExtractor(local, self.pool)
            isbn = fallback.extract_isbn()
            if isbn is None:
                issn = fallback.extract_issn()

        self.session.merge(
            FileText(
                file_id=file.id,
                barcode=barcode.raw_value if barcode else None,
                isbn=isbn,
                issn=issn,
                sample_pages=pages,
            )
        )

    # -- bookkeeping ---------------------------------------------------------

    def _record_error(
        self, file: File, stage: ProcessingStage, error: Exception
    ) -> None:
        assert file.id is not None
        text = record_error(self.session, file.id, stage, error).replace(
            self._local_copy, self._share_path
        )
        self._store_error_text(file.id, stage, text)
        log_file_fields(**{f"error_{stage.value}": text[:200]})
        mark_file_error(text)

    def _store_error_text(
        self, file_id: int, stage: ProcessingStage, text: str
    ) -> None:
        row = self.session.get(Error, (file_id, stage))
        if row is not None:
            row.error_text = text
            self.session.add(row)

    def _clear_errors(self, file: File) -> None:
        assert file.id is not None
        for stage in _SCAN_STAGES:
            clear_error(self.session, file.id, stage)

    def _clear_scan_rows(self, file: File) -> None:
        for table in (*_SCAN_TABLES, FileTextAnalysis):
            row = self.session.get(table, file.id)
            if row is not None:
                self.session.delete(row)
        self.session.flush()

    # -- hash join -----------------------------------------------------------

    def _find_moved(self, sha256: str) -> File | None:
        """A missing row with this hash whose old path is still absent."""
        candidates = self.session.exec(
            select(File)
            .where(col(File.sha256) == sha256)
            .where(col(File.missing_since).is_not(None))
            .order_by(col(File.missing_since))
        ).all()
        for candidate in candidates:
            root = self.session.get(Root, candidate.root_id)
            if (
                root is not None
                and not (Path(root.path) / candidate.relative_path).exists()
            ):
                return candidate
        return None

    def _apply_move(
        self, row: File, root: Root, relative: str, size: int, mtime: int, now: datetime
    ) -> File:
        log_file_fields(action="moved", moved_from=f"{row.root_id}:{row.relative_path}")
        assert root.id is not None
        row.root_id = root.id
        row.relative_path = relative
        row.size_bytes, row.mtime = size, mtime
        row.missing_since = None
        row.last_seen_at = now
        self.session.add(row)
        self.session.flush()
        self.stats.moved += 1
        return row

    def _join_duplicates(self, file: File) -> None:
        """Make every present copy of this content a duplicate of one winner.

        A library copy wins over a staging copy; among equals the earliest row
        wins. An LLM decision (`keep`, `superseded`, `discard`) is never overwritten.
        """
        rows = self.session.exec(
            select(File)
            .where(col(File.sha256) == file.sha256)
            .where(col(File.missing_since).is_(None))
            .order_by(col(File.id))
        ).all()
        if len(rows) < 2:
            return

        def rank(row: File) -> tuple[int, int]:
            in_library = row.root_id == self.library_root_id
            return (0 if in_library else 1, row.id or 0)

        winner = min(rows, key=rank)
        if winner.disposition is Disposition.duplicate:
            winner.disposition = Disposition.unfiled
            winner.duplicate_of_id = None
            self.session.add(winner)
        for row in rows:
            if row is winner:
                continue
            if row.disposition not in (Disposition.unfiled, Disposition.duplicate):
                continue  # an LLM decision stands
            if (
                row.disposition is Disposition.duplicate
                and row.duplicate_of_id == winner.id
            ):
                continue  # already recorded
            row.disposition = Disposition.duplicate
            row.duplicate_of_id = winner.id
            self.session.add(row)
            if row.id == file.id:
                self.stats.duplicates += 1
                log_file_fields(duplicate_of=winner.id)


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Scan every registered root, or only `--root PATH`."""
    pool = IsolatedWorkerPool()
    try:
        with session_scope(catalog_path) as session:
            roots = list(session.exec(select(Root).order_by(col(Root.id))).all())
            library = next((r for r in roots if r.kind is RootKind.library), None)
            if library is None:
                raise UsageError("The catalog has no library root. Run `init` first.")
            if args.root is not None:
                wanted = args.root.expanduser().resolve()
                roots = [r for r in roots if Path(r.path) == wanted]
                if not roots:
                    raise UsageError(f"{wanted} is not a registered root.")

            root_paths = [root.path for root in roots]  # read while the session is open
            scanner = Scanner(session, pool, force=args.force)
            scanner.library_root_id = library.id
            listings = {root.id: scanner.collect(root) for root in roots}
            for root in roots:
                listing = listings[root.id]
                if listing is not None:
                    scanner.mark_missing(root, set(listing))
            for root in roots:
                listing = listings[root.id]
                if listing is not None:
                    scanner.process_root(root, listing)
    finally:
        pool.close()

    s = scanner.stats
    log_call_fields(**vars(s), roots_scanned=root_paths)
    print(
        f"seen {s.seen}, skipped {s.skipped}, processed {s.processed}, "
        f"moved {s.moved}, duplicates {s.duplicates}, missing {s.missing}, "
        f"errors {s.errored}"
    )
    for path in s.unreachable_roots:
        print(f"warning: root {path} is unreachable; its files were not marked missing")
    return 0
