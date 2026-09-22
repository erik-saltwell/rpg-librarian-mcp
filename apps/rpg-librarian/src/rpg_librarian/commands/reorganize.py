"""`reorganize`: make the share match the catalog.

The catalog is master. For every filed file this computes where it belongs (see
`services.placement`), compares that with where it is, and moves the difference. It is a
diff of desired against actual state, not a replay of a log, so it is idempotent: a
second run with nothing changed moves nothing, and an interrupted run is simply re-run.

Safety rules, in order:

- Nothing is ever overwritten. A destination that already exists, or that two files both
  want, blocks the files involved: each gets an `error` row saying why, and nothing is
  renamed to make room.
- Before moving, the file at the recorded path must still have the size and modified
  time `scan` recorded. If not, it changed since the catalog last saw it: it is flagged,
  not moved.
- Same-volume moves are a rename. Across volumes (a dump on one share, the library on
  another) the file is copied, verified by SHA-256, and only then is the source removed.
- The only thing ever deleted is a source that was just copied and verified, and folders
  left empty by the moves. Nothing is deleted automatically otherwise: trash is emptied
  by hand.

`reorganize` writes only bookkeeping (the file's root, path, and `last_seen_at`), never
product assignments.
"""

from __future__ import annotations

import argparse
import errno
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import delete
from sqlmodel import Session, col, select

from rpg_librarian_tools.files import generate_sha256

from ..db import session_scope
from ..error_rows import clear_error, record_error
from ..errors import UsageError
from ..model import Error, File, ProcessingStage, Root, RootKind
from ..observability import (
    FileTracker,
    log_call_fields,
    log_file_fields,
    mark_file_error,
)
from ..paths import TRASH_DIRNAME
from ..progress import track
from ..services.placement import Placement, compute_placements

_PARTIAL_SUFFIX = ".rpg-librarian-partial"


@dataclass
class Stats:
    settled: int = 0
    moved: int = 0
    renamed: int = 0
    copied: int = 0
    trashed: int = 0
    blocked: int = 0
    errors: int = 0
    not_attempted: int = 0  # left for later by --limit
    unreachable: int = 0  # in a root that is offline
    dirs_removed: int = 0
    dry_run: bool = False
    blocked_reasons: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Check:
    verdict: str  # "ok" | "defer" | "blocked"
    reason: str = ""


def _source_of(placement: Placement) -> Path:
    return Path(placement.root_path) / placement.relative_path


def _display(placement: Placement, labels: dict[int, str]) -> str:
    return f"{labels[placement.root_id]}:{placement.relative_path}"


def _check(placement: Placement, library: Path, pending_sources: set[Path]) -> Check:
    """Whether `placement` can move right now. Reads the filesystem, changes nothing."""
    source = _source_of(placement)
    try:
        stat = source.stat()
    except OSError:
        return Check("blocked", "the file is not at its recorded path (run `scan`)")
    if stat.st_size != placement.size_bytes or int(stat.st_mtime) != placement.mtime:
        return Check(
            "blocked",
            "the file changed since the last scan (size or modified time); "
            "run `scan` first",
        )
    dest = library / placement.dest
    if dest.exists():
        if dest.resolve() in pending_sources:
            return Check("defer")  # occupied by a file that is itself about to move
        return Check("blocked", "something already exists at the destination")
    return Check("ok")


def _collisions(placements: list[Placement]) -> dict[int, str]:
    """Files whose destination is also wanted by, or already held by, another file."""
    by_dest: dict[str, list[Placement]] = defaultdict(list)
    for placement in placements:
        by_dest[placement.dest_key].append(placement)
    blocked: dict[int, str] = {}
    for group in by_dest.values():
        if len(group) < 2:
            continue
        for placement in group:
            if placement.settled:
                continue
            others = sorted(o.file_id for o in group if o.file_id != placement.file_id)
            blocked[placement.file_id] = (
                f"same destination as file(s) {others}: {placement.dest}"
            )
    return blocked


def _copy_verified(placement: Placement, source: Path, dest: Path) -> None:
    """Copy `source` to `dest`, prove the copy is identical, then remove the source."""
    partial = dest.with_name(dest.name + _PARTIAL_SUFFIX)
    partial.unlink(missing_ok=True)
    expected = placement.sha256 or generate_sha256(source)
    try:
        shutil.copy2(source, partial)
        if generate_sha256(partial) != expected:
            raise OSError("the copy does not match the original (SHA-256 differs)")
        os.replace(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    source.unlink()


def _move(placement: Placement, library: Path) -> str:
    """Move one file into place; returns the method used (`rename` or `copy`)."""
    source, dest = _source_of(placement), library / placement.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(source, dest)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        _copy_verified(placement, source, dest)
        return "copy"
    return "rename"


def _prune_empty_dirs(dirs: set[Path], boundaries: set[Path]) -> int:
    """Remove folders the moves left empty, climbing toward (never past) their root."""
    removed = 0
    for start in sorted(dirs, key=lambda d: len(d.parts), reverse=True):
        current = start
        while current not in boundaries and current.name != TRASH_DIRNAME:
            if not any(current.is_relative_to(b) for b in boundaries):
                break
            try:
                current.rmdir()
            except OSError:
                break  # not empty, or gone: stop climbing
            removed += 1
            current = current.parent
    return removed


def _new_top_level_folders(planned: list[Placement], library: Path) -> list[str]:
    seen: dict[str, None] = {}
    for placement in planned:
        top = PurePosixPath(placement.dest).parts[0]
        if top != TRASH_DIRNAME and not (library / top).exists():
            seen[top] = None
    return sorted(seen)


def _print_plan(
    planned: list[Placement],
    blocked: dict[int, str],
    unreachable: list[Placement],
    by_id: dict[int, Placement],
    labels: dict[int, str],
    library: Path,
    stats: Stats,
) -> None:
    groups: dict[str, list[Placement]] = defaultdict(list)
    for placement in planned:
        key = "MOVE (keep)" if placement.kind == "keep" else "TRASH"
        if placement.kind == "trash":
            key = f"TRASH ({PurePosixPath(placement.dest).parts[1]})"
        groups[key].append(placement)
    print(
        f"Plan (dry run): {len(planned)} to move, {len(blocked)} blocked, "
        f"{stats.settled} already in place"
        + (f", {len(unreachable)} in an unreachable root" if unreachable else "")
    )
    for key in sorted(groups):
        print(f"\n{key}: {len(groups[key])}")
        for placement in groups[key]:
            print(f"  {_display(placement, labels)}  ->  {placement.dest}")
    if blocked:
        print(f"\nBLOCKED: {len(blocked)} (nothing will be moved for these)")
        for file_id, reason in sorted(blocked.items()):
            print(f"  file {file_id}  {_display(by_id[file_id], labels)}\n    {reason}")
    if unreachable:
        print("\nUNREACHABLE ROOTS (skipped, nothing recorded):")
        for path in sorted({p.root_path for p in unreachable}):
            print(f"  {path}")
    new = _new_top_level_folders(planned, library)
    if new:
        print(f"\nNEW TOP-LEVEL FOLDERS (do not exist under the library yet): {new}")
    if not planned and not blocked:
        print("\nNothing to do: the share already matches the catalog.")


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Move files to where the catalog says they belong (`--dry-run` to preview)."""
    if args.limit is not None and args.limit < 1:
        raise UsageError("--limit must be at least 1.")
    stats = Stats(dry_run=args.dry_run)

    with session_scope(catalog_path) as session:
        roots = {root.id: root for root in session.exec(select(Root)).all() if root.id}
        library_root = next(
            (r for r in roots.values() if r.kind is RootKind.library), None
        )
        if library_root is None:
            raise UsageError("The catalog has no library root. Run `init` first.")
        library = Path(library_root.path)
        if not library.is_dir():
            raise UsageError(f"The library root {library} is not reachable.")
        labels = {
            rid: root.label or Path(root.path).name for rid, root in roots.items()
        }
        reachable = {rid for rid, root in roots.items() if Path(root.path).is_dir()}

        placements = compute_placements(session)
        by_id = {p.file_id: p for p in placements}
        stats.settled = sum(1 for p in placements if p.settled)
        todo = [p for p in placements if not p.settled]
        unreachable = [p for p in todo if p.root_id not in reachable]
        stats.unreachable = len(unreachable)
        todo = [p for p in todo if p.root_id in reachable]

        collided = _collisions(placements)
        blocked: dict[int, str] = {}
        candidates: list[Placement] = []
        pending_sources = {_source_of(p).resolve() for p in todo}
        for placement in todo:
            if placement.file_id in collided:
                blocked[placement.file_id] = collided[placement.file_id]
                continue
            check = _check(placement, library, pending_sources)
            if check.verdict == "blocked":
                blocked[placement.file_id] = check.reason
            else:
                candidates.append(placement)

        if args.dry_run:
            stats.blocked = len(blocked)
            _print_plan(candidates, blocked, unreachable, by_id, labels, library, stats)
            log_call_fields(**_loggable(stats), planned=len(candidates))
            return 0

        _execute(
            session,
            candidates,
            blocked,
            library,
            library_root,
            roots,
            labels,
            args,
            stats,
        )

    _print_summary(stats)
    log_call_fields(**_loggable(stats))
    return 0


def _loggable(stats: Stats) -> dict[str, object]:
    return {k: v for k, v in vars(stats).items() if k != "blocked_reasons"}


def _execute(
    session: Session,
    candidates: list[Placement],
    blocked: dict[int, str],
    library: Path,
    library_root: Root,
    roots: dict[int, Root],
    labels: dict[int, str],
    args: argparse.Namespace,
    stats: Stats,
) -> None:
    """Record the blocked files, then move the rest, retrying files whose destination
    is held by another file that is itself about to move (a swap or a chain)."""
    # `reorganize` errors are a snapshot of the last run: what is still blocked is
    # re-derived below. Clearing first means a file that has since been fixed, or moved
    # by hand and rescanned, does not keep an error it will never be visited to lose.
    session.exec(delete(Error).where(col(Error.stage) == ProcessingStage.reorganize))
    for file_id, reason in sorted(blocked.items()):
        _record_blocked(session, file_id, reason, stats)
    session.commit()

    boundaries = {Path(root.path) for root in roots.values()}
    emptied: set[Path] = set()
    remaining = list(candidates)
    attempts = 0

    with track("reorganize", len(candidates)) as progress:
        done = 0
        while remaining:
            progressed = False
            deferred: list[Placement] = []
            pending_sources = {_source_of(p).resolve() for p in remaining}
            for placement in remaining:
                if args.limit is not None and attempts >= args.limit:
                    deferred.append(placement)
                    stats.not_attempted += 1
                    continue
                check = _check(placement, library, pending_sources)
                if check.verdict == "defer":
                    deferred.append(placement)
                    continue
                progressed = True
                attempts += 1
                if check.verdict == "blocked":
                    _record_blocked(session, placement.file_id, check.reason, stats)
                else:
                    _apply(session, placement, library_root, library, emptied, stats)
                session.commit()  # one file, one transaction
                done += 1
                progress(
                    done, _display(placement, labels), stats.errors + stats.blocked
                )
            if args.limit is not None and attempts >= args.limit:
                break
            if not progressed:  # only chains that never resolve are left
                for placement in deferred:
                    _record_blocked(
                        session,
                        placement.file_id,
                        "its destination is held by a file that cannot move",
                        stats,
                    )
                session.commit()
                break
            remaining = deferred
    stats.dirs_removed = _prune_empty_dirs(emptied, boundaries)


def _record_blocked(session: Session, file_id: int, reason: str, stats: Stats) -> None:
    file = session.get(File, file_id)
    path = Path(file.relative_path) if file else Path(str(file_id))
    with FileTracker(file_id, path, action="blocked"):
        record_error(session, file_id, ProcessingStage.reorganize, RuntimeError(reason))
        log_file_fields(reason=reason)
        mark_file_error(reason)
    stats.blocked += 1
    stats.blocked_reasons[file_id] = reason


def _apply(
    session: Session,
    placement: Placement,
    library_root: Root,
    library: Path,
    emptied: set[Path],
    stats: Stats,
) -> None:
    source = _source_of(placement)
    action = "trashed" if placement.kind == "trash" else "moved"
    try:
        with FileTracker(
            placement.file_id,
            source,
            action=action,
            dest=placement.dest,
            from_root=placement.root_id,
        ):
            method = _move(placement, library)
            log_file_fields(method=method)
            file = session.get(File, placement.file_id)
            assert file is not None and library_root.id is not None
            file.root_id = library_root.id
            file.relative_path = placement.dest
            file.last_seen_at = datetime.now(UTC)
            session.add(file)
            clear_error(session, placement.file_id, ProcessingStage.reorganize)
    except Exception as error:
        session.rollback()
        record_error(session, placement.file_id, ProcessingStage.reorganize, error)
        stats.errors += 1
        return
    emptied.add(source.parent)
    if placement.kind == "trash":
        stats.trashed += 1
    else:
        stats.moved += 1
    if method == "rename":
        stats.renamed += 1
    else:
        stats.copied += 1


def _print_summary(stats: Stats) -> None:
    print(
        f"moved {stats.moved}, trashed {stats.trashed} "
        f"({stats.renamed} renamed, {stats.copied} copied), "
        f"blocked {stats.blocked}, errors {stats.errors}, "
        f"already in place {stats.settled}, empty folders removed {stats.dirs_removed}"
    )
    if stats.not_attempted:
        print(f"{stats.not_attempted} more left for another run (--limit)")
    if stats.unreachable:
        print(
            f"warning: {stats.unreachable} file(s) are in an unreachable root; skipped"
        )
    for file_id, reason in sorted(stats.blocked_reasons.items()):
        print(f"  blocked: file {file_id}: {reason}")
