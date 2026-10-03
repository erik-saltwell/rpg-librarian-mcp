"""Moving files into and out of packs, keeping the "entry or pack, never both" rule.

A file is an item of its own (a `file` entry) or a pack member (`file.pack_id`, no
entry). Every change of membership goes through here, so the rule, the normalization of
a member (`unfiled`, no stored subpath), and the deletion of a pack that has no members
left happen the same way for `scan`, `find-packs`, and the pack tools.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, col, select

from .entries import ensure_file_entry, optional_file_entry
from .model import (
    Disposition,
    Entry,
    File,
    FolderJudgment,
    FolderOutcome,
    Pack,
)
from .model.core import utc_now


@dataclass(frozen=True)
class Dropped:
    """A decision that was given up when a filed loose file joined a pack."""

    entry_id: int  # the file's former entry, now deleted
    relative_path: str
    disposition: Disposition
    product_id: int | None


def join(session: Session, file: File, pack: Pack) -> Dropped | None:
    """Make `file` a member of `pack`. Deletes its own entry (cascading its evidence,
    text analysis, errors, and review flags) and normalizes it to `unfiled` with no
    stored subpath. Returns the decision that was dropped, if the file was filed.

    A member of another pack moves to this one; that pack is deleted if this was its
    last member. Callers check eligibility (not a duplicate, not missing) first.
    """
    assert file.id is not None and pack.id is not None
    dropped: Dropped | None = None
    previous_pack = file.pack_id
    entry = optional_file_entry(session, file.id)
    if entry is not None:
        assert entry.id is not None
        if file.disposition is not Disposition.unfiled or entry.product_id is not None:
            dropped = Dropped(
                entry.id, file.relative_path, file.disposition, entry.product_id
            )
        session.delete(entry)
    file.pack_id = pack.id
    file.disposition = Disposition.unfiled
    file.subpath = None
    session.add(file)
    session.flush()
    if previous_pack is not None and previous_pack != pack.id:
        delete_if_empty(session, previous_pack)
    return dropped


def detach(
    session: Session, file: File, folders: list[tuple[int, str]] | None = None
) -> Entry:
    """Take `file` out of its pack: it becomes an unfiled item with a new entry. The
    pack is deleted if this was its last member (see `delete_if_empty`: `folders`)."""
    pack_id = file.pack_id
    file.pack_id = None
    file.disposition = Disposition.unfiled
    file.subpath = None
    session.add(file)
    session.flush()
    entry = ensure_file_entry(session, file)
    if pack_id is not None:
        delete_if_empty(session, pack_id, folders)
    return entry


def member_count(session: Session, pack_id: int) -> int:
    return session.exec(
        select(func.count()).select_from(File).where(col(File.pack_id) == pack_id)
    ).one()


def delete_if_empty(
    session: Session, pack_id: int, folders: list[tuple[int, str]] | None = None
) -> bool:
    """Delete a pack with no members left, with its entry and everything keyed by it
    (the database cascades from `pack` to `entry` to evidence, errors, and flags).

    Its folders (where it was formed, any `find-packs` answer that formed it, and
    `folders`, such as its current root) are recorded as dissolved, so `find-packs`
    does not form it again while they are unchanged: a dissolved pack is a correction.
    """
    if member_count(session, pack_id):
        return False
    pack = session.get(Pack, pack_id)
    if pack is not None:
        places = {(pack.root_id, pack.original_root_path), *(folders or [])}
        for judgment in session.exec(
            select(FolderJudgment).where(col(FolderJudgment.pack_id) == pack_id)
        ).all():
            places.add((judgment.root_id, judgment.folder))
        record_dissolved(session, sorted(places))
        entry = session.exec(select(Entry).where(col(Entry.pack_id) == pack_id)).first()
        if entry is not None:
            session.delete(entry)
            session.flush()
        session.delete(pack)
        session.flush()
    return True


def record_dissolved(session: Session, places: list[tuple[int, str]]) -> None:
    """Mark folders whose pack was dissolved as `no_packs` at their current contents."""
    from .find_packs.evidence import folder_fingerprint  # imports the model only

    for root_id, folder in places:
        if not folder:
            continue  # a whole root is never a pack candidate
        row = session.exec(
            select(FolderJudgment)
            .where(col(FolderJudgment.root_id) == root_id)
            .where(col(FolderJudgment.folder) == folder)
        ).first()
        if row is None:
            row = FolderJudgment(
                root_id=root_id,
                folder=folder,
                fingerprint="",
                outcome=FolderOutcome.no_packs,
            )
        row.fingerprint = folder_fingerprint(session, root_id, folder)
        row.outcome = FolderOutcome.no_packs
        row.reason = "a pack here was dissolved by hand or by scan; not re-formed"
        row.details = None
        row.pack_id = None
        row.judged_at = utc_now()
        session.add(row)
    session.flush()


def own_entry(session: Session, file: File) -> Entry:
    """The file's own entry, detaching it from its pack first if it is a member: what
    a stage needs before recording an error against the file itself."""
    if file.pack_id is not None:
        return detach(session, file)
    return ensure_file_entry(session, file)
