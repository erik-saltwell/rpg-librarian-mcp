"""Hash-only inbox cleanup: catalog and trash duplicates, never survivors."""

from __future__ import annotations

import argparse
import os
import stat as stat_types
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select as sql_select
from sqlmodel import Session, col, select

from rpg_librarian_tools.files import generate_sha256

from ..db import session_scope
from ..entries import ensure_file_entry
from ..errors import UsageError
from ..infrastructure.walk import is_filtered
from ..model import Disposition, File, Root, RootKind
from ..observability import (
    FileTracker,
    log_call_fields,
    log_file_fields,
    mark_file_error,
)
from ..paths import desired_trash_path
from ..progress import track
from ..services.duplicates import duplicate_rank
from ..services.filename_policy import PathAllocator
from ..services.placement import Placement
from .reorganize import PackFailures, Stats, apply_placement, check_placement


@dataclass(frozen=True)
class Copy:
    path: Path
    size: int
    mtime: int
    file_id: int | None = None
    mtime_ns: int | None = None

    def present(self) -> bool:
        try:
            stat = self.path.stat()
            return (
                stat_types.S_ISREG(stat.st_mode)
                and stat.st_size == self.size
                and int(stat.st_mtime) == self.mtime
                and (self.mtime_ns is None or stat.st_mtime_ns == self.mtime_ns)
            )
        except OSError:
            return False


@dataclass
class DedupeStats:
    seen: int = 0
    hashed: int = 0
    bytes_read: int = 0
    survivors: int = 0
    duplicates: int = 0
    errors: int = 0
    dry_run: bool = False


def _collect(base: Path) -> list[Path]:
    def fail(error: OSError) -> None:
        raise UsageError(f"Cannot enumerate inbox: {error}") from error

    paths: list[Path] = []
    for folder, directories, files in os.walk(base, onerror=fail, followlinks=False):
        parent = Path(folder)
        directories[:] = sorted(
            name
            for name in directories
            if not is_filtered(parent / name) and not (parent / name).is_symlink()
        )
        paths.extend(
            parent / name for name in sorted(files) if not is_filtered(parent / name)
        )
    return paths


def _signature(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


class Deduper:
    def __init__(
        self,
        session: Session,
        root: Root,
        library: Root,
        roots: dict[int, Root],
        dry_run: bool,
    ) -> None:
        assert root.id is not None and library.id is not None
        self.session = session
        self.root = root
        self.library_root = library
        self.base = Path(root.path)
        self.library = Path(library.path)
        self.stats = DedupeStats(dry_run=dry_run)
        self.moves = Stats(dry_run=dry_run)
        self.emptied: set[Path] = set()
        self.failures = PackFailures()
        self.incoming: dict[str, Copy] = {}
        self.known: dict[str, list[Copy]] = defaultdict(list)
        self.known_sizes: set[int] = set()
        self.existing: dict[str, tuple[int, Disposition, int | None]] = {}
        current: dict[int, str] = {}
        rows = (
            session.connection()
            .execute(
                sql_select(
                    col(File.id),
                    col(File.root_id),
                    col(File.relative_path),
                    col(File.sha256),
                    col(File.size_bytes),
                    col(File.mtime),
                    col(File.missing_since),
                    col(File.pack_id),
                    col(File.disposition),
                    col(File.duplicate_of_id),
                )
            )
            .all()
        )
        ranked = sorted(
            rows, key=lambda r: duplicate_rank(r[7], r[1], r[0] or 0, library.id)
        )
        for (
            fid,
            rid,
            relative,
            digest,
            size,
            mtime,
            missing,
            pack,
            disposition,
            original,
        ) in ranked:
            assert fid is not None
            if rid == library.id:
                current[fid] = relative
            if rid == root.id:
                self.existing[relative] = (fid, disposition, pack)
                continue
            if digest is None or missing is not None or rid not in roots:
                continue
            # Inbox-only duplicates have no cataloged original. They must not eat
            # their uncataloged survivor on a rerun before normal scan links it.
            if disposition is Disposition.duplicate and original is None:
                continue
            self.known[digest].append(
                Copy(Path(roots[rid].path) / relative, size, mtime, fid)
            )
            self.known_sizes.add(size)
        self.allocator = PathAllocator(current, self.library)

    def process(self, paths: list[Path]) -> None:
        for path in paths:
            existing = self.existing.get(path.relative_to(self.base).as_posix())
            if existing is not None and (
                existing[1] is not Disposition.duplicate or existing[2] is not None
            ):
                raise UsageError(
                    f"{path} is already cataloged and is not a retryable duplicate. "
                    "Use an uncataloged inbox; "
                    "quick-dedupe leaves survivors uncataloged."
                )

        candidates: list[tuple[Path, os.stat_result]] = []
        for path in paths:
            try:
                if path.is_symlink():
                    raise OSError("symbolic links are not processed")
                stat = path.stat()
                if not stat_types.S_ISREG(stat.st_mode):
                    raise OSError("only regular files are processed")
                candidates.append((path, stat))
            except OSError as error:
                self.stats.seen += 1
                self._error(path, error)
        sizes = Counter(stat.st_size for _, stat in candidates)
        # Uncataloged originals must be considered before pending duplicate rows.
        candidates.sort(
            key=lambda item: item[0].relative_to(self.base).as_posix() in self.existing
        )
        with track("quick-dedupe", len(candidates)) as progress:
            for index, (path, stat) in enumerate(candidates, start=1):
                self.stats.seen += 1
                relative = path.relative_to(self.base).as_posix()
                existing = self.existing.get(relative)
                with FileTracker(
                    existing[0] if existing else None, path, action="dedupe"
                ):
                    try:
                        self._one(path, relative, stat, sizes[stat.st_size], existing)
                    except (OSError, ValueError) as error:
                        self._error(path, error)
                progress(
                    index,
                    relative,
                    self.stats.errors + self.moves.errors + self.moves.blocked,
                )

    def _one(
        self,
        path: Path,
        relative: str,
        stat: os.stat_result,
        same_size: int,
        existing: tuple[int, Disposition, int | None] | None,
    ) -> None:
        if _signature(path.stat()) != _signature(stat):
            raise OSError(
                "file changed while the inbox was enumerated; rerun quick-dedupe"
            )
        if stat.st_size not in self.known_sizes and same_size == 1 and existing is None:
            self.stats.survivors += 1
            log_file_fields(result="unique_size", size_bytes=stat.st_size)
            return
        digest = generate_sha256(path)
        self.stats.hashed += 1
        self.stats.bytes_read += stat.st_size
        if _signature(path.stat()) != _signature(stat):
            raise OSError("file changed while hashing; rerun quick-dedupe")
        log_file_fields(sha256=digest, size_bytes=stat.st_size)
        file = self.session.get(File, existing[0]) if existing else None
        if existing is not None and (
            file is None
            or file.root_id != self.root.id
            or file.relative_path != relative
            or file.disposition is not Disposition.duplicate
            or file.pack_id is not None
        ):
            raise OSError(
                "pending duplicate's catalog record changed; rerun quick-dedupe"
            )
        if file is not None and file.sha256 is not None and file.sha256 != digest:
            raise OSError(
                "pending duplicate's content changed; use scan to reconcile it"
            )

        winner = next(
            (copy for copy in self.known.get(digest, []) if copy.present()), None
        )
        if winner is None:
            winner = self.incoming.get(digest)
            if winner is not None and not winner.present():
                winner = None
        if winner is None:
            if existing is not None:
                raise OSError(
                    "pending duplicate has no available original; leave it in place "
                    "and restore the original or use scan to reconcile it"
                )
            self.incoming[digest] = Copy(
                path, stat.st_size, int(stat.st_mtime), mtime_ns=stat.st_mtime_ns
            )
            self.stats.survivors += 1
            log_file_fields(result="survivor")
            return

        self.stats.duplicates += 1
        log_file_fields(
            result="duplicate",
            duplicate_of=winner.file_id,
            original_path=str(winner.path),
        )
        if self.stats.dry_run:
            fid = existing[0] if existing else -self.stats.seen
            dest = self._destination(fid, relative)
            print(f"DUPLICATE {path} -> {self.library / dest}")
            return

        assert self.root.id is not None
        file = file or File(
            root_id=self.root.id,
            relative_path=relative,
            size_bytes=stat.st_size,
            mtime=int(stat.st_mtime),
        )
        file.sha256 = digest
        file.size_bytes, file.mtime = stat.st_size, int(stat.st_mtime)
        file.last_seen_at = datetime.now(UTC)
        file.missing_since = None
        file.disposition = Disposition.duplicate
        file.duplicate_of_id = winner.file_id
        self.session.add(file)
        self.session.flush()
        entry = ensure_file_entry(self.session, file)
        assert file.id is not None and entry.id is not None and self.root.id is not None
        placement = Placement(
            file_id=file.id,
            entry_id=entry.id,
            disposition=Disposition.duplicate,
            kind="trash",
            root_id=self.root.id,
            root_path=str(self.base),
            root_is_library=False,
            relative_path=relative,
            size_bytes=stat.st_size,
            mtime=int(stat.st_mtime),
            sha256=digest,
            dest=self._destination(file.id, relative),
            settled=False,
        )
        # Durable recovery record exists even if the move or its bookkeeping fails.
        self.session.commit()
        check = check_placement(placement, self.library, set())
        if check.verdict != "ok":
            raise OSError(check.reason)
        if not winner.present():
            raise OSError(
                "original disappeared or changed before the duplicate could move"
            )
        if _signature(path.stat()) != _signature(stat):
            raise OSError("file changed before moving; rerun quick-dedupe")
        previous_errors = self.moves.errors
        apply_placement(
            self.session,
            placement,
            self.library_root,
            self.library,
            self.emptied,
            self.moves,
            self.failures,
        )
        if self.moves.errors > previous_errors:
            print(f"ERROR {path}: move failed; see its reorganize error in the catalog")
        self.session.commit()

    def _destination(self, file_id: int, relative: str) -> str:
        assert self.root.id is not None
        desired = str(
            desired_trash_path(
                "duplicates",
                root_id=self.root.id,
                root_path=str(self.base),
                root_is_library=False,
                relative_path=relative,
            )
        )
        return self.allocator.allocate(file_id, desired)

    def _error(self, path: Path, error: Exception) -> None:
        self.stats.errors += 1
        mark_file_error(str(error))
        print(f"ERROR {path}: {error}")


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    wanted = args.root.expanduser().resolve()
    if not wanted.is_dir():
        raise UsageError(f"Inbox {wanted} is not an existing directory.")
    with session_scope(catalog_path, migrate=not args.dry_run) as session:
        roots = {r.id: r for r in session.exec(select(Root)).all() if r.id is not None}
        library = next((r for r in roots.values() if r.kind is RootKind.library), None)
        if library is None or not Path(library.path).is_dir():
            raise UsageError(
                "The catalog needs a reachable library root. Run init first."
            )
        root = next((r for r in roots.values() if Path(r.path) == wanted), None)
        if root is None or root.kind is not RootKind.staging:
            raise UsageError(
                "--root must be a registered staging root. Run add-source PATH first."
            )
        deduper = Deduper(session, root, library, roots, args.dry_run)
        deduper.process(_collect(wanted))
        stats, moves = deduper.stats, deduper.moves
        errors = stats.errors + moves.errors + moves.blocked
        print(
            f"{'dry run: ' if args.dry_run else ''}seen {stats.seen}, "
            f"hashed {stats.hashed} ({stats.bytes_read} bytes), "
            f"duplicates {stats.duplicates}, survivors {stats.survivors}, "
            f"trashed {moves.trashed} "
            f"({moves.renamed} renamed, {moves.copied} copied), "
            f"errors {errors}"
        )
        if errors:
            print(
                "Resolve errors and rerun before moving inbox contents to holding-pen."
            )
        log_call_fields(**vars(stats), trashed=moves.trashed, move_errors=moves.errors)
        return 1 if errors else 0
