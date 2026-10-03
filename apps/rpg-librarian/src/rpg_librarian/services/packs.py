"""The pack tools: create a pack by hand, add or remove its files, and report it.

Members have no entry id and file ids never reach the LLM, so files are named by path:
a root-relative file or folder path (a folder means every file below it), with
`root_id` when the path exists under several roots. Every call is one transaction; a
failure raises `UsageError` and the caller rolls the whole call back.

Rules (see `membership`):
- Automatic duplicates are never members: a folder's duplicates are skipped and
  reported, a duplicate named on its own is refused. Files missing from the share are
  skipped the same way.
- A filed loose file may join a pack; the decision it gives up is reported in
  `dropped_decisions`. A member of another pack moves; a pack left with no members is
  deleted.
- A file removed from a pack becomes an ordinary unfiled entry.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlmodel import Session, col, select

from ..entries import entries_with_packs, optional_file_entry
from ..errors import UsageError
from ..membership import Dropped, detach, join
from ..model import (
    Disposition,
    DtrpgResult,
    Entry,
    EntryType,
    Error,
    File,
    FileTextAnalysis,
    GoogleSearchResult,
    Pack,
    PackFormation,
    ReviewFlag,
    Root,
    RpggeekResult,
)
from .pack_info import PackView, pack_views
from .pending import pending_changes
from .reports import _row, analysis_hint, product_ref
from .update_product import UpdateProductRequest, update_product

_SAMPLE_FILENAMES = 5
_PACK_EVIDENCE = {
    "dtrpg": DtrpgResult,
    "rpggeek": RpggeekResult,
    "google": GoogleSearchResult,
}


# -- resolving paths ----------------------------------------------------------


def _clean(path: str) -> str:
    cleaned = path.strip().strip("/")
    return "" if cleaned in ("", ".") else cleaned


@dataclass
class _Selection:
    """The files a path names, split by whether they can be members."""

    root_id: int
    path: str
    is_folder: bool
    files: list[File] = field(default_factory=list)
    duplicates: list[File] = field(default_factory=list)
    missing: list[File] = field(default_factory=list)


def _select(session: Session, path: str, root_id: int | None) -> _Selection:
    """The cataloged files at `path` (one file) or below it (a folder)."""
    wanted = _clean(path)
    roots = {r.id: r for r in session.exec(select(Root)).all()}
    if root_id is not None and root_id not in roots:
        raise UsageError(f"No root with id {root_id}.")
    statement = select(File)
    if root_id is not None:
        statement = statement.where(col(File.root_id) == root_id)
    if wanted:
        prefix = wanted.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        statement = statement.where(
            (col(File.relative_path) == wanted)
            | col(File.relative_path).like(prefix + "/%", escape="\\")
        )
    found = session.exec(statement.order_by(col(File.relative_path))).all()
    by_root: dict[int, list[File]] = defaultdict(list)
    for file in found:
        by_root[file.root_id].append(file)
    if not by_root:
        where = f" in root {root_id}" if root_id is not None else ""
        raise UsageError(f"Nothing in the catalog at {wanted or '(root)'!r}{where}.")
    if len(by_root) > 1:
        raise UsageError(f"{wanted!r} exists in roots {sorted(by_root)}; pass root_id.")
    chosen, files = next(iter(by_root.items()))
    is_folder = not (len(files) == 1 and files[0].relative_path == wanted)
    selection = _Selection(root_id=chosen, path=wanted, is_folder=is_folder)
    for file in files:
        if file.missing_since is not None:
            selection.missing.append(file)
        elif file.disposition is Disposition.duplicate and file.pack_id is None:
            selection.duplicates.append(file)
        else:
            selection.files.append(file)
    if not is_folder:
        if selection.duplicates:
            raise UsageError(
                f"{wanted!r} is an automatic duplicate; duplicates are never pack "
                "members. File the original instead."
            )
        if selection.missing:
            raise UsageError(
                f"{wanted!r} is missing from the share; run `scan` again first."
            )
    return selection


def _load_pack(session: Session, entry_id: int) -> tuple[Entry, Pack]:
    found = entries_with_packs(session, [entry_id]).get(entry_id)
    if found is None:
        raise UsageError(f"No entry with id {entry_id}.")
    entry, pack = found
    if entry.type is not EntryType.pack or pack is None:
        raise UsageError(
            f"Entry {entry_id} is a {entry.type.value} entry, not a pack. "
            "Use create-pack to make a pack from a folder."
        )
    return entry, pack


def _dropped_json(
    session: Session, dropped: list[Dropped], entry: Entry, pack: Pack
) -> list[dict[str, Any]]:
    """The decisions given up: those that differ from the pack's own."""
    kept = (pack.disposition, entry.product_id)
    return [
        {
            "former_entry_id": d.entry_id,
            "relative_path": d.relative_path,
            "disposition": d.disposition.value,
            "product": product_ref(session, d.product_id),
        }
        for d in dropped
        if (d.disposition, d.product_id) != kept
    ]


def _skipped_json(selection: _Selection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if selection.duplicates:
        out["skipped_duplicates"] = [f.relative_path for f in selection.duplicates]
    if selection.missing:
        out["skipped_missing"] = [f.relative_path for f in selection.missing]
    return out


def _join_all(
    session: Session, files: list[File], pack: Pack
) -> tuple[list[Dropped], Counter[int]]:
    """Join every file; returns dropped decisions and how many came from each pack."""
    dropped: list[Dropped] = []
    moved_from: Counter[int] = Counter()
    for file in files:
        if file.pack_id == pack.id:
            continue
        if file.pack_id is not None:
            moved_from[file.pack_id] += 1
        result = join(session, file, pack)
        if result is not None:
            dropped.append(result)
    return dropped, moved_from


# -- create -------------------------------------------------------------------


def _shared_decision(
    session: Session, files: list[File]
) -> tuple[Disposition, int | None] | None:
    """The (disposition, product) every file already has, or None if they differ.

    A loose file's decision is its own; a member's is its pack's. All unfiled counts as
    agreeing on unfiled.
    """
    decisions: set[tuple[Disposition, int | None]] = set()
    pack_ids = {f.pack_id for f in files if f.pack_id is not None}
    views = pack_views(session, [p for p in pack_ids if p is not None])
    for file in files:
        if file.pack_id is not None:
            view = views[file.pack_id]
            decisions.add((view.pack.disposition, view.entry.product_id))
        else:
            assert file.id is not None
            entry = optional_file_entry(session, file.id)
            product_id = entry.product_id if entry is not None else None
            if file.disposition is Disposition.unfiled:
                product_id = None
            decisions.add((file.disposition, product_id))
    return decisions.pop() if len(decisions) == 1 else None


def create_pack(
    session: Session,
    *,
    folder: str,
    root_id: int | None = None,
    disposition: Disposition | None = None,
    product_type: str | None = None,
    product_line: str | None = None,
    product: str | None = None,
    create_line: bool = False,
    create_type: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Make the files below `folder` one pack, by hand (no LLM, never re-judged).

    Without a decision the pack takes the one its files already share (unfiled when
    they are all unfiled). If they differ, give `disposition` (and the product for
    `keep`), exactly as for `update_product`.
    """
    selection = _select(session, folder, root_id)
    if not selection.is_folder:
        raise UsageError(
            f"{selection.path!r} is a file. A pack is made from a folder; use "
            "add-to-pack to add one file to an existing pack."
        )
    if not selection.files:
        raise UsageError(
            f"No files below {selection.path!r} can be pack members (all are "
            "duplicates or missing)."
        )
    given = disposition is not None
    shared = _shared_decision(session, selection.files)
    if not given and shared is None:
        decisions = sorted(
            {
                f"{f.relative_path}: {f.disposition.value}"
                for f in selection.files
                if f.pack_id is None and f.disposition is not Disposition.unfiled
            }
        )[:5]
        raise UsageError(
            "Nothing was changed. The files below this folder are filed differently "
            f"(for example {decisions}), so the pack's decision must be given: pass "
            "disposition (and product_type, product_line, product for keep). The "
            "decisions the files give up are then reported."
        )

    pack = Pack(
        root_id=selection.root_id,
        original_root_path=selection.path,
        formation=PackFormation.create_pack,
        reason=reason or "created by hand with create-pack",
    )
    session.add(pack)
    session.flush()
    entry = Entry(type=EntryType.pack, pack_id=pack.id)
    session.add(entry)
    session.flush()
    assert entry.id is not None
    dropped, moved_from = _join_all(session, selection.files, pack)

    filing: dict[str, Any] | None = None
    if given:
        filing = update_product(
            session,
            UpdateProductRequest(
                entry_ids=[entry.id],
                disposition=disposition,
                product_type=product_type,
                product_line=product_line,
                product=product,
                create_line=create_line,
                create_type=create_type,
            ),
        )
    elif shared is not None and shared[0] is not Disposition.unfiled:
        # The files' shared decision becomes the pack's: nothing is lost.
        pack.disposition, entry.product_id = shared
        dropped = []
        session.add(pack)
        session.add(entry)
        if shared[0] is Disposition.keep and shared[1] is not None:
            _check_shared_kept(session, pack, shared[1])
    session.flush()
    return {
        "pack": _summary(session, entry.id),
        "moved_from_packs": {
            str(k): v for k, v in sorted(moved_from.items())
        },  # by former pack id; those left empty were deleted
        "dropped_decisions": _dropped_json(session, dropped, entry, pack),
        **_skipped_json(selection),
        **({"filing": filing} if filing else {}),
    }


def _check_shared_kept(session: Session, pack: Pack, product_id: int) -> None:
    other = session.exec(
        select(Entry)
        .join(Pack, col(Pack.id) == col(Entry.pack_id))
        .where(col(Entry.product_id) == product_id)
        .where(col(Pack.disposition) == Disposition.keep)
        .where(col(Pack.id) != pack.id)
    ).first()
    if other is not None:
        raise UsageError(
            f"Nothing was changed. The files' product already has a kept pack (entry "
            f"{other.id}). Add these files to that pack with add-to-pack instead."
        )


# -- add and remove -----------------------------------------------------------


def add_to_pack(
    session: Session, *, entry_id: int, path: str, root_id: int | None = None
) -> dict[str, Any]:
    """Add the file at `path`, or every file below a folder, to the pack `entry_id`.

    Members of another pack move here (a pack left empty is deleted); loose files give
    up their own entry, and any decision they had is reported in `dropped_decisions`.
    """
    entry, pack = _load_pack(session, entry_id)
    assert pack.id is not None
    if root_id is None:
        root_id = pack_views(session, [pack.id])[pack.id].root_id
    selection = _select(session, path, root_id)
    if not selection.files:
        raise UsageError(
            f"No file at or below {selection.path!r} can be added (all are duplicates "
            "or missing)."
        )
    already = [f for f in selection.files if f.pack_id == pack.id]
    dropped, moved_from = _join_all(session, selection.files, pack)
    session.flush()
    return {
        "pack": _summary(session, entry_id),
        "added": len(selection.files) - len(already),
        "already_members": len(already),
        "moved_from_packs": {str(k): v for k, v in sorted(moved_from.items())},
        "dropped_decisions": _dropped_json(session, dropped, entry, pack),
        **_skipped_json(selection),
    }


def remove_from_pack(
    session: Session, *, entry_id: int, path: str, root_id: int | None = None
) -> dict[str, Any]:
    """Take the member at `path`, or every member below a folder, out of the pack.

    Each becomes an ordinary unfiled file with a new entry id (listed). A pack left with
    no members is deleted with its entry and evidence.
    """
    _entry, pack = _load_pack(session, entry_id)
    assert pack.id is not None
    if root_id is None:
        root_id = pack_views(session, [pack.id])[pack.id].root_id
    selection = _select(session, path, root_id)
    members = [
        f for f in [*selection.files, *selection.missing] if f.pack_id == pack.id
    ]
    if not members:
        raise UsageError(
            f"No member of pack entry {entry_id} at or below {selection.path!r}."
        )
    removed: list[dict[str, Any]] = []
    pack_id = pack.id
    view = pack_views(session, [pack_id])[pack_id]
    for file in members:
        new_entry = detach(session, file, [(view.root_id, view.folder)])
        removed.append({"entry_id": new_entry.id, "relative_path": file.relative_path})
    session.flush()
    deleted = session.get(Pack, pack_id) is None
    return {
        "removed": removed,
        "pack_deleted": deleted,
        **({} if deleted else {"pack": _summary(session, entry_id)}),
    }


# -- report -------------------------------------------------------------------


def _members(session: Session, pack_id: int) -> list[File]:
    return list(
        session.exec(
            select(File)
            .where(col(File.pack_id) == pack_id)
            .order_by(col(File.root_id), col(File.relative_path))
        ).all()
    )


def _below(view: PackView, file: File) -> str:
    """A member's path below the pack's current root."""
    path = PurePosixPath(file.relative_path)
    if file.root_id == view.root_id and view.folder:
        try:
            return str(path.relative_to(view.folder))
        except ValueError:
            pass
    return file.relative_path


def _summary(session: Session, entry_id: int) -> dict[str, Any]:
    """A pack's identity and decision, small whatever its size (see `report_pack`)."""
    entry, pack = _load_pack(session, entry_id)
    assert pack.id is not None
    view = pack_views(session, [pack.id])[pack.id]
    members = [f for f in _members(session, pack.id) if f.missing_since is None]
    subfolders: Counter[str] = Counter()
    for file in members:
        parts = PurePosixPath(_below(view, file)).parts
        subfolders[parts[0] if len(parts) > 1 else ""] += 1
    root = session.get(Root, view.root_id)
    assert root is not None
    return {
        "entry": {"id": entry_id, "type": EntryType.pack.value},
        "pack": {
            "root": {"id": root.id, "kind": root.kind.value, "path": root.path},
            "folder": view.folder,
            "original_root": pack.original_root_path,
            "formation": pack.formation.value,
            "reason": pack.reason,
            "disposition": pack.disposition.value,
            "members": view.members,
            "missing_members": view.missing,
            "members_by_media_type": view.by_media_type,
            "subfolders": [
                {"folder": name, "files": count}
                for name, count in sorted(subfolders.items())
                if name
            ],
            "files_at_root": subfolders.get("", 0),
            "sample_filenames": [
                PurePosixPath(f.relative_path).name for f in members[:_SAMPLE_FILENAMES]
            ],
        },
        "product": product_ref(session, entry.product_id),
    }


def pack_report_entry(session: Session, entry_id: int) -> dict[str, Any]:
    """`report_entry` for a pack: its summary, evidence, errors, and review flag."""
    report = _summary(session, entry_id)
    open_flag = session.exec(
        select(ReviewFlag)
        .where(col(ReviewFlag.entry_id) == entry_id)
        .where(col(ReviewFlag.resolved_at).is_(None))
    ).first()
    report |= {
        "text_analysis": analysis_hint(
            session.get(FileTextAnalysis, entry_id), truncate=False
        ),
        "evidence": {
            name: _row(session.get(table, entry_id))
            for name, table in _PACK_EVIDENCE.items()
        },
        "errors": [
            {"stage": e.stage.value, "error": e.error_text, "at": e.occurred_at}
            for e in session.exec(
                select(Error).where(col(Error.entry_id) == entry_id)
            ).all()
        ],
        "review_flag": (
            {"reason": open_flag.reason, "opened_at": open_flag.created_at}
            if open_flag
            else None
        ),
        "pending_changes": pending_changes(session),
    }
    return report


def report_pack(session: Session, entry_id: int) -> dict[str, Any]:
    """Everything in a pack: every subfolder and every member file."""
    _entry, pack = _load_pack(session, entry_id)
    assert pack.id is not None
    view = pack_views(session, [pack.id])[pack.id]
    members = _members(session, pack.id)
    folders: Counter[str] = Counter()
    for file in members:
        if file.missing_since is not None:
            continue
        below = PurePosixPath(_below(view, file)).parent
        for depth in range(1, len(below.parts) + 1):
            folders["/".join(below.parts[:depth])] += 1
    return {
        **_summary(session, entry_id),
        "subdirectories": [
            {"folder": name, "subtree_files": count}
            for name, count in sorted(folders.items())
        ],
        "files": [
            {
                "root_id": f.root_id,
                "relative_path": f.relative_path,
                "path_in_pack": _below(view, f),
                "media_type": f.media_type.value if f.media_type else None,
                "size_bytes": f.size_bytes,
                **({"missing_since": f.missing_since} if f.missing_since else {}),
            }
            for f in members
        ],
    }
