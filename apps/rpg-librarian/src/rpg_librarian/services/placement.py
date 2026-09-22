"""Where every non-unfiled file belongs, and whether it is already there.

One function, `compute_placements`, is the single source of truth for both
`pending_changes` (how many files are out of place) and `reorganize` (moving them), so
a report and the next `reorganize --dry-run` cannot disagree.

Destinations are relative to the library root:

- `keep` files go to `<type>/<line>/[<product>/]<filename>` (see `paths`).
- `duplicate`, `superseded`, and `discard` files go under `.trash/<bucket>/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func
from sqlmodel import Session, col, select

from ..model import Disposition, File, Product, ProductLine, ProductType, Root, RootKind
from ..paths import (
    TRASH_BUCKETS,
    desired_trash_path,
    target_relative_path,
    trash_bucket_of,
)


@dataclass(frozen=True)
class Placement:
    file_id: int
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

    @property
    def dest_key(self) -> str:
        """Destination compared case-insensitively: SMB shares usually are."""
        return self.dest.casefold()


def compute_placements(session: Session) -> list[Placement]:
    """A placement for every filed file that has not gone missing, in file-id order."""
    roots = {root.id: root for root in session.exec(select(Root)).all()}
    kept_counts = dict(
        session.exec(
            select(col(File.product_id), func.count())
            .where(col(File.disposition) == Disposition.keep)
            .where(col(File.missing_since).is_(None))
            .group_by(col(File.product_id))
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
    files = session.exec(
        select(File)
        .where(col(File.disposition) != Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
        .order_by(col(File.id))
    ).all()
    for file in files:
        assert file.id is not None
        root = roots[file.root_id]
        in_library = root.kind is RootKind.library
        if file.disposition is Disposition.keep:
            if file.product_id is None or file.product_id not in names:
                continue  # the CHECK constraint makes this unreachable
            type_name, line_name, product_name = names[file.product_id]
            dest = str(
                target_relative_path(
                    type_name=type_name,
                    line_name=line_name,
                    product_name=product_name,
                    filename=file.relative_path.rsplit("/", 1)[-1],
                    kept_count=kept_counts.get(file.product_id, 0),
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
            )
        )
    return placements
