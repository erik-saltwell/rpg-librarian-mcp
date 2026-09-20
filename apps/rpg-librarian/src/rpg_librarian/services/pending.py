"""How far the share has drifted from the catalog.

`pending_changes` counts the files whose current location differs from the one the
catalog says they belong in. It is computed by the same functions `reorganize` uses,
so a report and the next `reorganize --dry-run` agree.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from ..model import Disposition, File, Product, ProductLine, ProductType, Root, RootKind
from ..paths import (
    TRASH_BUCKETS,
    desired_trash_path,
    target_relative_path,
    trash_bucket_of,
)


def pending_changes(session: Session) -> dict[str, Any]:
    """`{"total": n, "by_disposition": {"keep": a, "duplicate": b, ...}}`."""
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

    by_disposition: dict[str, int] = {}
    files = session.exec(
        select(File)
        .where(col(File.disposition) != Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
    ).all()
    for file in files:
        root = roots[file.root_id]
        in_library = root.kind is RootKind.library
        if file.disposition is Disposition.keep:
            if file.product_id is None or file.product_id not in names:
                continue  # the CHECK constraint makes this unreachable
            type_name, line_name, product_name = names[file.product_id]
            filename = file.relative_path.rsplit("/", 1)[-1]
            target = target_relative_path(
                type_name=type_name,
                line_name=line_name,
                product_name=product_name,
                filename=filename,
                kept_count=kept_counts.get(file.product_id, 0),
            )
            settled = in_library and file.relative_path == str(target)
        else:
            bucket = TRASH_BUCKETS[file.disposition]
            desired = desired_trash_path(
                bucket,
                root_id=file.root_id,
                root_path=root.path,
                root_is_library=in_library,
                relative_path=file.relative_path,
            )
            settled = trash_bucket_of(in_library, file.relative_path) == bucket or (
                in_library and file.relative_path == str(desired)
            )
        if not settled:
            by_disposition[file.disposition.value] = (
                by_disposition.get(file.disposition.value, 0) + 1
            )
    return {"total": sum(by_disposition.values()), "by_disposition": by_disposition}
