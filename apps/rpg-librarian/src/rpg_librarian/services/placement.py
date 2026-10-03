"""Where every non-unfiled file belongs, and whether it is already there.

One function, `compute_placements`, is the single source of truth for both
`pending_changes` (how many files are out of place) and `reorganize` (moving them), so
a report and the next `reorganize --dry-run` cannot disagree.

Destinations are relative to the library root:

- `keep` files go to `<type>/<line>/[<product>/]<subpath>` (see `paths`). A file's
  subpath is stored in the catalog once its product first moves; until then it is
  worked out from where the file sits (see `_kept_subpaths`).
- `duplicate`, `superseded`, and `discard` files go under `.trash/<bucket>/`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from sqlalchemy import func
from sqlmodel import Session, col, select

from ..model import (
    Disposition,
    Entry,
    File,
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
    trash_bucket_of,
)


@dataclass(frozen=True)
class Placement:
    file_id: int  # internal: which row moves
    entry_id: int  # what reports and error rows name
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

    @property
    def dest_key(self) -> str:
        """Destination compared case-insensitively: SMB shares usually are."""
        return self.dest.casefold()


def compute_placements(session: Session) -> list[Placement]:
    """A placement for every filed file that has not gone missing, in file-id order."""
    roots = {root.id: root for root in session.exec(select(Root)).all()}
    kept_counts = dict(
        session.exec(
            select(col(Entry.product_id), func.count())
            .select_from(File)
            .join(Entry, col(Entry.file_id) == col(File.id))
            .where(col(File.disposition) == Disposition.keep)
            .where(col(File.missing_since).is_(None))
            .group_by(col(Entry.product_id))
        ).all()
    )
    names = {
        product.id: (product_type.name, line.name, product.name)
        for product, line, product_type in session.exec(
            select(Product, ProductLine, ProductType)
            .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
            .join(ProductType, col(ProductType.id) == col(ProductLine.product_type_id))
        ).all()
    }

    placements: list[Placement] = []
    rows = session.exec(
        select(File, Entry)
        .join(Entry, col(Entry.file_id) == col(File.id))
        .where(col(File.disposition) != Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
        .order_by(col(File.id))
    ).all()
    files = [file for file, _ in rows]
    entries = {file.id: entry for file, entry in rows}
    products = {file_id: entry.product_id for file_id, entry in entries.items()}
    subpaths = _kept_subpaths(files, kept_counts, products)
    for file in files:
        assert file.id is not None
        entry = entries[file.id]
        assert entry.id is not None
        product_id = entry.product_id
        root = roots[file.root_id]
        in_library = root.kind is RootKind.library
        subpath: str | None = None
        derived = False
        group: tuple[int, int] | None = None
        if file.disposition is Disposition.keep:
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
            bucket = TRASH_BUCKETS[file.disposition]
            dest = str(
                desired_trash_path(
                    bucket,
                    root_id=file.root_id,
                    root_path=root.path,
                    root_is_library=in_library,
                    relative_path=file.relative_path,
                )
            )
            settled = trash_bucket_of(in_library, file.relative_path) == bucket
            kind = "trash"
        placements.append(
            Placement(
                file_id=file.id,
                entry_id=entry.id,
                disposition=file.disposition,
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
            )
        )
    return placements


def _kept_subpaths(
    files: Sequence[File],
    kept_counts: dict[int | None, int],
    products: dict[int | None, int | None],
) -> dict[int, tuple[PurePosixPath, bool]]:
    """Each kept file's path below its product folder, and whether it was worked out.

    A stored subpath is used as it is. The rest are worked out per product and root:
    a single-file product's file is just its filename. Otherwise the files are placed
    relative to their *source base*, the deepest folder holding all of them, so a
    pack's own subfolders (Day/Night, BW/Color) survive the move. If the base also
    holds other products' files it is a category folder like `Settings and
    Supplements/`, not the product's, and each file gets just its filename instead.
    """
    kept = [f for f in files if f.disposition is Disposition.keep and f.id is not None]
    # Per root, which products have kept files somewhere below each folder.
    products_below: dict[int, dict[PurePosixPath, set[int | None]]] = defaultdict(
        lambda: defaultdict(set)
    )
    groups: dict[tuple[int | None, int], list[File]] = defaultdict(list)
    subpaths: dict[int, tuple[PurePosixPath, bool]] = {}
    for file in kept:
        assert file.id is not None
        product_id = products[file.id]
        for folder in PurePosixPath(file.relative_path).parents:
            products_below[file.root_id][folder].add(product_id)
        if file.subpath is not None:
            subpaths[file.id] = (clean_subpath(PurePosixPath(file.subpath)), False)
        else:
            groups[(product_id, file.root_id)].append(file)

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
