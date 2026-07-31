from __future__ import annotations

from pathlib import Path

from fastmcp import Context
from sqlmodel import Session

from ..catalog import Catalog
from ..model import Entry, ProcessingStage
from .UpdateBaseCommand import UpdateBaseCommand, UpdateResult


class RemoveCommand(UpdateBaseCommand):
    """Move every entry under a path into `.catalog/trash/`, removing it
    from the catalog.

    Not a delete -- the file is relocated on disk, mirroring its
    library-relative path under `.catalog/trash/` (intermediate
    directories created as needed), and its `Entry` row is removed, since
    the file is no longer at a cataloged library path once moved.

    Built on `UpdateBaseCommand` for its shared entry-resolution/per-entry
    error-handling/progress-reporting machinery, not because removal has a
    staleness concept -- `should_process` is unconditionally true (an
    already-removed entry has no `Entry` row left to be resolved again on a
    later run), so `force` has no observable effect for this command.
    """

    def __init__(self, catalog: Catalog, max_errors: int = 50) -> None:
        super().__init__(catalog, ProcessingStage.remove, max_errors)
        self._directories_touched: set[Path] = set()

    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        ctx: Context,
    ) -> UpdateResult:
        """Same as the base `process`, plus pruning directories left empty
        by this run's removals.

        Only directories a file was actually removed from this run are
        candidates (tracked in `process_one`, via `_directories_touched`)
        -- an incidentally-empty, untouched sibling folder elsewhere in the
        library is not this call's business to delete. Pruning cascades
        upward while a parent also ends up empty, but never above
        `starting_path` itself -- that's the requested scope's own
        boundary, not "removes all files under the passed-in path"'s
        license to also sweep out that path's ancestors.
        """
        self._directories_touched = set()
        result = await super().process(starting_path, process_recursively, force, ctx)
        self._prune_empty_directories(starting_path)
        return result

    def should_process(self, session: Session, entry: Entry) -> bool:
        return True

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        trash_root = (self.catalog.catalog_dir / "trash").resolve()
        trash_path = (self.catalog.catalog_dir / "trash" / entry.path).resolve()
        # entry.path is normally validated (no ".." components, never
        # absolute) by ParentPathType on every bind -- but a row planted by
        # raw SQL (see conftest.insert_raw_entry / the poisoned_catalog
        # fixture) bypasses that. Refuse to move anything outside the
        # intended trash root rather than trusting a resolved path built
        # from unvalidated data.
        if trash_root != trash_path and trash_root not in trash_path.parents:
            raise ValueError(
                f"entry {entry.id} has a corrupt parent_path -- refusing to "
                f"move it outside {trash_root}"
            )
        if trash_path.exists():
            raise ValueError(f"{trash_path} already exists in the trash")

        # Queue the catalog change before the disk move (the unreliable
        # step) happens -- same "unreliable step last" ordering `move` uses.
        # If the rename below raises, UpdateBaseCommand's per-entry rollback
        # discards this queued delete, leaving the file and its Entry row
        # untouched rather than a phantom removed-but-not-moved row.
        session.delete(entry)

        trash_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.rename(trash_path)
        self._directories_touched.add(file_path.parent)

    def _prune_empty_directories(self, starting_path: Path) -> None:
        """Remove directories left empty by this run, deepest first, never
        going above `starting_path` itself.

        Always picking the *deepest remaining* candidate guarantees a
        directory's children (if also candidates) are resolved before it
        is -- e.g. `shelf/box` and `shelf/box/sub` can both be touched in
        the same run, and `shelf/box` must not be attempted (and fail,
        permanently, since a failure is never retried) while `sub` still
        sits inside it unresolved.

        A single-file `starting_path` has no directory scope to prune --
        removing one file emptying its folder is not license to also
        remove that folder, which was never part of what was asked for.
        """
        scope_root = self.catalog.to_absolute(self.catalog.to_relative(starting_path))
        if not scope_root.is_dir():
            return

        candidates = set(self._directories_touched)
        while candidates:
            directory = max(candidates, key=lambda p: len(p.parts))
            candidates.discard(directory)
            try:
                directory.rmdir()
            except OSError:
                continue
            if directory != scope_root:
                candidates.add(directory.parent)
