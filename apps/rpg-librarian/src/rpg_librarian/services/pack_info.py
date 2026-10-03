"""Read-only facts about packs that several reports and lists need.

A pack's *current root* is derived from its members, never stored: the deepest folder
holding all its present members, in the root where most of them are. `reorganize` moves
members, so a stored path would go stale; the original root (`pack.original_root_path`)
is kept separately as the record of where the pack was formed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlmodel import Session, col, select

from ..model import Entry, File, Pack


@dataclass
class PackView:
    pack: Pack
    entry: Entry
    root_id: int  # the root holding most present members (the pack's own if none)
    folder: str  # current root, relative to `root_id`; "" is the root itself
    members: int = 0  # present members
    missing: int = 0  # members missing from the share
    by_media_type: dict[str, int] = field(default_factory=dict)  # present members

    @property
    def entry_id(self) -> int:
        assert self.entry.id is not None
        return self.entry.id


def _media(file: File) -> str:
    return file.media_type.value if file.media_type else "unknown"


def common_folder(paths: list[str]) -> str:
    """The deepest folder holding every one of these root-relative file paths."""
    if not paths:
        return ""
    folders = [PurePosixPath(p).parent.parts for p in paths]
    common = folders[0]
    for parts in folders[1:]:
        n = 0
        while n < min(len(common), len(parts)) and common[n] == parts[n]:
            n += 1
        common = common[:n]
    return "/".join(common)


def pack_views(
    session: Session, pack_ids: list[int] | None = None
) -> dict[int, PackView]:
    """Every pack (or the given ones) with its derived location and member counts."""
    statement = select(Pack, Entry).join(Entry, col(Entry.pack_id) == col(Pack.id))
    if pack_ids is not None:
        if not pack_ids:
            return {}
        statement = statement.where(col(Pack.id).in_(pack_ids))
    packs = {pack.id: (pack, entry) for pack, entry in session.exec(statement).all()}
    member_query = select(File).where(col(File.pack_id).is_not(None))
    if pack_ids is not None:
        member_query = member_query.where(col(File.pack_id).in_(pack_ids))
    present: dict[int, list[File]] = defaultdict(list)
    missing: Counter[int] = Counter()
    for file in session.exec(member_query).all():
        assert file.pack_id is not None
        if file.missing_since is None:
            present[file.pack_id].append(file)
        else:
            missing[file.pack_id] += 1

    views: dict[int, PackView] = {}
    for pack_id, (pack, entry) in packs.items():
        assert pack_id is not None
        files = present.get(pack_id, [])
        if files:
            root_id = Counter(f.root_id for f in files).most_common(1)[0][0]
            folder = common_folder(
                [f.relative_path for f in files if f.root_id == root_id]
            )
        else:
            root_id, folder = pack.root_id, pack.original_root_path
        views[pack_id] = PackView(
            pack=pack,
            entry=entry,
            root_id=root_id,
            folder=folder,
            members=len(files),
            missing=missing[pack_id],
            by_media_type=dict(Counter(_media(f) for f in files)),
        )
    return views
