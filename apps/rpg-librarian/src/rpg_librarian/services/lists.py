"""The worklist and the coordinate lookups: what is left to file, and what exists."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import exists, func
from sqlmodel import Session, col, select

from ..errors import UsageError
from ..model import (
    Disposition,
    File,
    FileTextAnalysis,
    PdfMetadata,
    Product,
    ProductLine,
    ProductLineAlias,
    ProductType,
    ReviewFlag,
    Root,
)
from .names import normalize_name
from .reports import analysis_hint

DEFAULT_LIMIT = 100


def _folder_of(relative_path: str) -> str:
    parent = str(PurePosixPath(relative_path).parent)
    return "" if parent == "." else parent


def _clean_folder(folder: str | None) -> str | None:
    if folder is None:
        return None
    cleaned = folder.strip().strip("/")
    return "" if cleaned in ("", ".") else cleaned


def _is_within(folder: str, ancestor: str) -> bool:
    return ancestor == "" or folder == ancestor or folder.startswith(ancestor + "/")


def list_unfiled(
    session: Session,
    *,
    folder: str | None = None,
    root_id: int | None = None,
    recursive: bool = False,
    include_flagged: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """The worklist of files no one has filed yet.

    Without `folder`: every folder that holds unfiled files, with counts. With
    `folder`: that folder's own unfiled files plus its subfolders (all descendants
    when `recursive`). Files already resolved never appear: automatic duplicates,
    files missing from the share, and, unless `include_flagged`, files the LLM
    deferred with an open review flag.
    """
    if limit < 1:
        raise UsageError("limit must be at least 1.")
    roots = {root.id: root for root in session.exec(select(Root)).all()}
    if root_id is not None and root_id not in roots:
        raise UsageError(f"No root with id {root_id}.")

    statement = (
        select(File)
        .where(col(File.disposition) == Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
        .order_by(col(File.root_id), col(File.relative_path))
    )
    if root_id is not None:
        statement = statement.where(col(File.root_id) == root_id)
    if not include_flagged:
        statement = statement.where(
            ~exists().where(
                col(ReviewFlag.file_id) == col(File.id),
                col(ReviewFlag.resolved_at).is_(None),
            )
        )
    files = session.exec(statement).all()

    direct: dict[tuple[int, str], int] = defaultdict(int)
    subtree: dict[tuple[int, str], int] = defaultdict(int)
    for file in files:
        where = _folder_of(file.relative_path)
        direct[(file.root_id, where)] += 1
        parts = PurePosixPath(where).parts if where else ()
        for depth in range(len(parts) + 1):
            subtree[(file.root_id, "/".join(parts[:depth]))] += 1

    wanted = _clean_folder(folder)
    if wanted is None:
        entries = [
            {
                "root_id": rid,
                "root_kind": roots[rid].kind.value,
                "folder": where,
                "direct_files": direct.get((rid, where), 0),
                "subtree_files": count,
            }
            for (rid, where), count in sorted(subtree.items())
        ]
        return {
            "total_unfiled_files": len(files),
            "folders": entries[:limit],
            "truncated": len(entries) > limit,
        }

    matching_roots = sorted({rid for (rid, where) in subtree if where == wanted})
    if root_id is None and len(matching_roots) > 1:
        raise UsageError(
            f"Folder {wanted!r} has unfiled files in roots {matching_roots}; "
            "pass root_id."
        )
    if not matching_roots:
        return {
            "root_id": root_id,
            "folder": wanted,
            "files": [],
            "subfolders": [],
            "total_files": 0,
            "truncated": False,
        }
    chosen = matching_roots[0]

    in_scope = [
        f
        for f in files
        if f.root_id == chosen
        and (
            _is_within(_folder_of(f.relative_path), wanted)
            if recursive
            else _folder_of(f.relative_path) == wanted
        )
    ]
    page = in_scope[:limit]
    ids = [f.id for f in page if f.id is not None]
    analyses = {
        a.file_id: a
        for a in session.exec(
            select(FileTextAnalysis).where(col(FileTextAnalysis.file_id).in_(ids))
        ).all()
    }
    pdfs = {
        p.file_id: p
        for p in session.exec(
            select(PdfMetadata).where(col(PdfMetadata.file_id).in_(ids))
        ).all()
    }
    flagged = set(
        session.exec(
            select(col(ReviewFlag.file_id))
            .where(col(ReviewFlag.file_id).in_(ids))
            .where(col(ReviewFlag.resolved_at).is_(None))
        ).all()
    )

    prefix = wanted + "/" if wanted else ""
    children: dict[str, int] = defaultdict(int)
    for (rid, where), count in subtree.items():
        if rid == chosen and where != wanted and where.startswith(prefix):
            first = where[len(prefix) :].split("/", 1)[0]
            if where == prefix + first:
                children[where] = count
    return {
        "root_id": chosen,
        "root_kind": roots[chosen].kind.value,
        "folder": wanted,
        "files": [
            {
                "id": f.id,
                "relative_path": f.relative_path,
                "media_type": f.media_type.value if f.media_type else None,
                "size_bytes": f.size_bytes,
                "pages": pdfs[f.id].page_count if f.id in pdfs else None,
                "text_analysis": analysis_hint(analyses.get(f.id), truncate=True),
                **({"open_review_flag": f.id in flagged} if include_flagged else {}),
            }
            for f in page
        ],
        "subfolders": [
            {"folder": name, "subtree_files": count}
            for name, count in sorted(children.items())
        ],
        "total_files": len(in_scope),
        "truncated": len(in_scope) > limit,
    }


def list_product_types(session: Session) -> dict[str, Any]:
    """Every product type with counts of its lines, products, and kept files."""
    types = session.exec(select(ProductType).order_by(col(ProductType.name))).all()
    lines = dict(
        session.exec(
            select(col(ProductLine.product_type_id), func.count()).group_by(
                col(ProductLine.product_type_id)
            )
        ).all()
    )
    products = dict(
        session.exec(
            select(col(ProductLine.product_type_id), func.count())
            .select_from(Product)
            .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
            .group_by(col(ProductLine.product_type_id))
        ).all()
    )
    kept = dict(
        session.exec(
            select(col(ProductLine.product_type_id), func.count())
            .select_from(File)
            .join(Product, col(Product.id) == col(File.product_id))
            .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
            .where(col(File.disposition) == Disposition.keep)
            .group_by(col(ProductLine.product_type_id))
        ).all()
    )
    return {
        "types": [
            {
                "id": t.id,
                "name": t.name,
                "lines": lines.get(t.id, 0),
                "products": products.get(t.id, 0),
                "kept_files": kept.get(t.id, 0),
            }
            for t in types
        ]
    }


def list_product_lines(
    session: Session,
    *,
    product_type: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Product lines with their type, aliases, and product counts.

    `search` matches line names and aliases case-insensitively, so "D&D 5e" finds
    "Dungeons & Dragons" before anyone creates a second line for it.
    """
    if limit < 1:
        raise UsageError("limit must be at least 1.")
    types = {t.id: t for t in session.exec(select(ProductType)).all()}
    statement = select(ProductLine).order_by(
        col(ProductLine.product_type_id), col(ProductLine.name)
    )
    if product_type is not None:
        wanted = normalize_name(product_type)
        match = next(
            (t for t in types.values() if normalize_name(t.name) == wanted), None
        )
        if match is None:
            raise UsageError(
                f"No product type {product_type!r}. "
                f"Types: {sorted(t.name for t in types.values())}."
            )
        statement = statement.where(col(ProductLine.product_type_id) == match.id)
    lines = session.exec(statement).all()

    aliases: dict[int, list[str]] = defaultdict(list)
    for alias in session.exec(select(ProductLineAlias)).all():
        aliases[alias.product_line_id].append(alias.alias)
    product_counts = dict(
        session.exec(
            select(col(Product.product_line_id), func.count()).group_by(
                col(Product.product_line_id)
            )
        ).all()
    )

    needle = normalize_name(search) if search else None
    rows = []
    for line in lines:
        assert line.id is not None
        names = [line.name, *aliases.get(line.id, [])]
        if needle and not any(needle in normalize_name(n) for n in names):
            continue
        rows.append(
            {
                "id": line.id,
                "type": types[line.product_type_id].name,
                "name": line.name,
                "aliases": sorted(aliases.get(line.id, [])),
                "products": product_counts.get(line.id, 0),
            }
        )
    return {"lines": rows[:limit], "total": len(rows), "truncated": len(rows) > limit}
