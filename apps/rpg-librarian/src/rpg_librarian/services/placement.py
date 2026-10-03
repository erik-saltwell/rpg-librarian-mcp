"""Where every non-unfiled file belongs, and whether it is already there.

One function, `compute_placements`, is the single source of truth for both
`pending_changes` (how many files are out of place) and `reorganize` (moving them), so
a report and the next `reorganize --dry-run` cannot disagree.

Destinations are relative to the library root:

- `keep` files go to `<type>/<line>/[<product>/]<subpath>` (see `paths`). A file's
  subpath is stored in the catalog once its product first moves; until then it is
  worked out from where the file sits (see `_kept_subpaths`).
- A pack's members are placed by the pack's disposition and product.
- `duplicate`, `superseded`, and `discard` files go under `.trash/<bucket>/`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from sqlmodel import Session, col, select

from ..model import (
    Disposition,
    Entry,
    File,
    Pack,
    Product,
    ProductLine,
    ProductType,
    Root,
    RootKind,
)
from ..paths import (
    TRASH_BUCKETS,
    clean_subpath,
    desired_trash_path,
    target_relative_path,
)
from .filename_policy import allocate_paths


@dataclass(frozen=True)
class Placement:
    file_id: int  # internal: which row moves
    entry_id: int  # what reports and error rows name: the file's entry, or its pack's
    disposition: Disposition
    kind: Literal["keep", "trash"]
    root_id: int
    root_path: str
    root_is_library: bool
    relative_path: str  # where the file is now, relative to its root
    size_bytes: int  # as recorded by the last scan, to notice a changed source
    mtime: int
    sha256: str | None
    dest: str  # where it belongs, relative to the library root
    settled: bool  # already there
    # Kept files only: the path below the product folder, and whether it was worked
    # out this time (True) or read from the catalog (False).
    subpath: str | None = None
    subpath_derived: bool = False
    # Kept files only: (product id, root id). A product's files in one root have their
    # worked-out subpaths stored together (see `reorganize`).
    group: tuple[int, int] | None = None
    # Pack members only: the pack whose decision placed the file (`entry_id` is then the
    # pack's entry).
    pack_id: int | None = None

    @property
    def dest_key(self) -> str:
        """Destination compared case-insensitively: SMB shares usually are."""
        return self.dest.casefold()


@dataclass(frozen=True)
class _Item:
    """A filed, present file with the decision that applies to it: its own (a file
    entry) or its pack's (a member)."""

    file: File
    entry_id: int
    disposition: Disposition
    product_id: int | None
    pack_id: int | None = None


def _filed_items(session: Session) -> list[_Item]:
    """Every filed file that has not gone missing, in file-id order: files with their
    own entry, and pack members, which take their pack's disposition and product."""
    items: list[_Item] = []
    for file, entry in session.exec(
        select(File, Entry)
        .join(Entry, col(Entry.file_id) == col(File.id))
        .where(col(File.disposition) != Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
    ).all():
        assert entry.id is not None
        items.append(_Item(file, entry.id, file.disposition, entry.product_id))
    for file, pack, entry in session.exec(
        select(File, Pack, Entry)
        .join(Pack, col(Pack.id) == col(File.pack_id))
        .join(Entry, col(Entry.pack_id) == col(Pack.id))
        .where(col(Pack.disposition) != Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
    ).all():
        assert entry.id is not None
        items.append(_Item(file, entry.id, pack.disposition, entry.product_id, pack.id))
    items.sort(key=lambda item: item.file.id or 0)
    return items


def compute_placements(session: Session) -> list[Placement]:
    """A placement for every filed file that has not gone missing, in file-id order.

    A pack member is placed by its pack's decision: its disposition and product.
    """
    roots = {root.id: root for root in session.exec(select(Root)).all()}
    items = _filed_items(session)
    kept_counts: dict[int | None, int] = defaultdict(int)
    for item in items:
        if item.disposition is Disposition.keep:
            kept_counts[item.product_id] += 1
    names = {
        product.id: (product_type.name, line.name, product.name)
        for product, line, product_type in session.exec(
            select(Product, ProductLine, ProductType)
            .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
            .join(ProductType, col(ProductType.id) == col(ProductLine.product_type_id))
        ).all()
    }

    placements: list[Placement] = []
    subpaths = _kept_subpaths(items, kept_counts)
    for item in items:
        file = item.file
        assert file.id is not None
        product_id = item.product_id
        root = roots[file.root_id]
        in_library = root.kind is RootKind.library
        subpath: str | None = None
        derived = False
        group: tuple[int, int] | None = None
        if item.disposition is Disposition.keep:
            if product_id is None or product_id not in names:
                continue  # `update_product` never keeps a file without a product
            type_name, line_name, product_name = names[product_id]
            kept_subpath, derived = subpaths[file.id]
            subpath = str(kept_subpath)
            group = (product_id, file.root_id)
            dest = str(
                target_relative_path(
                    type_name=type_name,
                    line_name=line_name,
                    product_name=product_name,
                    subpath=kept_subpath,
                    kept_count=kept_counts.get(product_id, 0),
                )
            )
            settled = in_library and file.relative_path == dest
            kind: Literal["keep", "trash"] = "keep"
        else:
            bucket = TRASH_BUCKETS[item.disposition]
            dest = str(
                desired_trash_path(
                    bucket,
                    root_id=file.root_id,
                    root_path=root.path,
                    root_is_library=in_library,
                    relative_path=file.relative_path,
                )
            )
            settled = in_library and file.relative_path == dest
            kind = "trash"
        placements.append(
            Placement(
                file_id=file.id,
                entry_id=item.entry_id,
                disposition=item.disposition,
                kind=kind,
                root_id=file.root_id,
                root_path=root.path,
                root_is_library=in_library,
                relative_path=file.relative_path,
                size_bytes=file.size_bytes,
                mtime=file.mtime,
                sha256=file.sha256,
                dest=dest,
                settled=settled,
                subpath=subpath,
                subpath_derived=derived,
                group=group,
                pack_id=item.pack_id,
            )
        )
    library_root = next((r for r in roots.values() if r.kind is RootKind.library), None)
    if library_root is None:
        return placements
    current = {
        f.id: f.relative_path
        for f in session.exec(select(File).where(File.root_id == library_root.id)).all()
        if f.id is not None
    }
    allocated = allocate_paths(
        {p.file_id: p.dest for p in placements},
        current,
        Path(library_root.path),
        preferred={
            p.file_id
            for p in placements
            if PurePosixPath(p.relative_path).name == PurePosixPath(p.dest).name
        },
    )
    result = []
    for p in placements:
        dest = allocated[p.file_id]
        subpath = p.subpath
        if subpath is not None:
            subpath = str(PurePosixPath(subpath).with_name(PurePosixPath(dest).name))
        result.append(
            replace(
                p,
                dest=dest,
                subpath=subpath,
                subpath_derived=p.subpath_derived or subpath != p.subpath,
                settled=p.root_is_library and p.relative_path == dest,
            )
        )
    return result


def _kept_subpaths(
    items: Sequence[_Item], kept_counts: dict[int | None, int]
) -> dict[int, tuple[PurePosixPath, bool]]:
    """Each kept file's path below its product folder, and whether it was worked out.

    A stored subpath is used as it is. The rest are worked out per product and root:
    a single-file product's file is just its filename. Otherwise the files are placed
    relative to their *source base*, the deepest folder holding all of them, so a
    pack's own subfolders (Day/Night, BW/Color) survive the move. If the base also
    holds other products' files it is a category folder like `Settings and
    Supplements/`, not the product's, and each file gets just its filename instead.

    A pack member is placed relative to its pack's current root: the deepest folder
    holding all the pack's members in that root. The pack is the product, so its
    folder structure below that root is kept as it is.
    """
    kept = [i for i in items if i.disposition is Disposition.keep and i.file.id]
    # Per root, which products have kept files somewhere below each folder.
    products_below: dict[int, dict[PurePosixPath, set[int | None]]] = defaultdict(
        lambda: defaultdict(set)
    )
    groups: dict[tuple[int | None, int], list[File]] = defaultdict(list)
    pack_groups: dict[tuple[int, int], list[File]] = defaultdict(list)
    pack_members: dict[tuple[int, int], list[File]] = defaultdict(list)
    subpaths: dict[int, tuple[PurePosixPath, bool]] = {}
    for item in kept:
        file = item.file
        assert file.id is not None
        for folder in PurePosixPath(file.relative_path).parents:
            products_below[file.root_id][folder].add(item.product_id)
        if item.pack_id is not None:
            pack_members[(item.pack_id, file.root_id)].append(file)
        if file.subpath is not None:
            cleaned = clean_subpath(PurePosixPath(file.subpath))
            subpaths[file.id] = (cleaned, str(cleaned) != file.subpath)
        elif item.pack_id is not None:
            pack_groups[(item.pack_id, file.root_id)].append(file)
        else:
            groups[(item.product_id, file.root_id)].append(file)

    for (product_id, root_id), group in groups.items():
        paths = [PurePosixPath(f.relative_path) for f in group]
        base = _common_folder([p.parent for p in paths])
        flat = kept_counts.get(product_id, 0) <= 1 or bool(
            products_below[root_id][base] - {product_id}
        )
        for file, path in zip(group, paths, strict=True):
            assert file.id is not None
            subpath = PurePosixPath(path.name) if flat else path.relative_to(base)
            subpaths[file.id] = (clean_subpath(subpath), True)

    for key, group in pack_groups.items():
        members = pack_members[key]
        base = _common_folder([PurePosixPath(f.relative_path).parent for f in members])
        for file in group:
            assert file.id is not None
            subpath = PurePosixPath(file.relative_path).relative_to(base)
            subpaths[file.id] = (clean_subpath(subpath), True)
    return subpaths


def _common_folder(folders: list[PurePosixPath]) -> PurePosixPath:
    """The deepest folder containing all of `folders` (`.` when only the root does)."""
    common = folders[0].parts
    for folder in folders[1:]:
        parts = folder.parts
        n = 0
        while n < min(len(common), len(parts)) and common[n] == parts[n]:
            n += 1
        common = common[:n]
    return PurePosixPath(*common)
