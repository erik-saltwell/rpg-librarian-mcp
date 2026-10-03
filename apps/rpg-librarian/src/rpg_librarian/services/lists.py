"""The worklist and the coordinate lookups: what is left to file, and what exists."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import exists, func
from sqlmodel import Session, col, select

from ..errors import UsageError
from ..model import (
    Disposition,
    Entry,
    File,
    FileTextAnalysis,
    Pack,
    PdfMetadata,
    Product,
    ProductLine,
    ProductLineAlias,
    ProductType,
    ReviewFlag,
    Root,
)
from .names import normalize_name
from .pack_info import PackView, pack_views
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
    """The worklist of files and packs no one has filed yet.

    Without `folder`: every folder that holds unfiled files or packs, with counts. With
    `folder`: that folder's own unfiled files and packs plus its subfolders (all
    descendants when `recursive`). Files already resolved never appear: automatic
    duplicates, files missing from the share, pack members (their pack is the item),
    and, unless `include_flagged`, items the LLM deferred with an open review flag. A
    pack is listed in the folder that is its current root.
    """
    if limit < 1:
        raise UsageError("limit must be at least 1.")
    roots = {root.id: root for root in session.exec(select(Root)).all()}
    if root_id is not None and root_id not in roots:
        raise UsageError(f"No root with id {root_id}.")

    statement = (
        select(File, Entry)
        .join(Entry, col(Entry.file_id) == col(File.id))
        .where(col(File.disposition) == Disposition.unfiled)
        .where(col(File.missing_since).is_(None))
        .order_by(col(File.root_id), col(File.relative_path))
    )
    if root_id is not None:
        statement = statement.where(col(File.root_id) == root_id)
    if not include_flagged:
        statement = statement.where(
            ~exists().where(
                col(ReviewFlag.entry_id) == col(Entry.id),
                col(ReviewFlag.resolved_at).is_(None),
            )
        )
    rows = session.exec(statement).all()
    files = [file for file, _ in rows]
    entry_of = {file.id: entry.id for file, entry in rows}
    packs = _unfiled_packs(session, root_id, include_flagged)

    direct: dict[tuple[int, str], int] = defaultdict(int)
    subtree: dict[tuple[int, str], int] = defaultdict(int)
    for file in files:
        where = _folder_of(file.relative_path)
        direct[(file.root_id, where)] += 1
        parts = PurePosixPath(where).parts if where else ()
        for depth in range(len(parts) + 1):
            subtree[(file.root_id, "/".join(parts[:depth]))] += 1
    direct_packs: dict[tuple[int, str], int] = defaultdict(int)
    subtree_packs: dict[tuple[int, str], int] = defaultdict(int)
    for view in packs:
        direct_packs[(view.root_id, view.folder)] += 1
        parts = PurePosixPath(view.folder).parts if view.folder else ()
        for depth in range(len(parts) + 1):
            subtree_packs[(view.root_id, "/".join(parts[:depth]))] += 1
    folders_with_items = sorted(set(subtree) | set(subtree_packs))

    wanted = _clean_folder(folder)
    if wanted is None:
        entries = [
            {
                "root_id": rid,
                "root_kind": roots[rid].kind.value,
                "folder": where,
                "direct_files": direct.get((rid, where), 0),
                "subtree_files": subtree.get((rid, where), 0),
                **(
                    {
                        "direct_packs": direct_packs.get((rid, where), 0),
                        "subtree_packs": subtree_packs[(rid, where)],
                    }
                    if (rid, where) in subtree_packs
                    else {}
                ),
            }
            for rid, where in folders_with_items
        ]
        return {
            "total_unfiled_files": len(files),
            "total_unfiled_packs": len(packs),
            "folders": entries[:limit],
            "truncated": len(entries) > limit,
        }

    matching_roots = sorted(
        {rid for (rid, where) in folders_with_items if where == wanted}
    )
    if root_id is None and len(matching_roots) > 1:
        raise UsageError(
            f"Folder {wanted!r} has unfiled items in roots {matching_roots}; "
            "pass root_id."
        )
    if not matching_roots:
        return {
            "root_id": root_id,
            "folder": wanted,
            "files": [],
            "packs": [],
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
    entry_ids = [entry_of[i] for i in ids]
    analyses = {
        a.entry_id: a
        for a in session.exec(
            select(FileTextAnalysis).where(
                col(FileTextAnalysis.entry_id).in_(entry_ids)
            )
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
            select(col(ReviewFlag.entry_id))
            .where(col(ReviewFlag.entry_id).in_(entry_ids))
            .where(col(ReviewFlag.resolved_at).is_(None))
        ).all()
    )

    pack_scope = [
        view
        for view in packs
        if view.root_id == chosen
        and (_is_within(view.folder, wanted) if recursive else view.folder == wanted)
    ]
    pack_analyses = {
        a.entry_id: a
        for a in session.exec(
            select(FileTextAnalysis).where(
                col(FileTextAnalysis.entry_id).in_([v.entry_id for v in pack_scope])
            )
        ).all()
    }

    prefix = wanted + "/" if wanted else ""
    children: list[str] = []
    for rid, where in folders_with_items:
        if rid == chosen and where != wanted and where.startswith(prefix):
            first = where[len(prefix) :].split("/", 1)[0]
            if where == prefix + first:
                children.append(where)
    return {
        "root_id": chosen,
        "root_kind": roots[chosen].kind.value,
        "folder": wanted,
        "files": [
            {
                "entry_id": entry_of[f.id],
                "relative_path": f.relative_path,
                "media_type": f.media_type.value if f.media_type else None,
                "size_bytes": f.size_bytes,
                "pages": pdfs[f.id].page_count if f.id in pdfs else None,
                "text_analysis": analysis_hint(
                    analyses.get(entry_of[f.id]), truncate=True
                ),
                **(
                    {"open_review_flag": entry_of[f.id] in flagged}
                    if include_flagged
                    else {}
                ),
            }
            for f in page
        ],
        "packs": [
            {
                "entry_id": view.entry_id,
                "folder": view.folder,
                "members": view.members,
                "members_by_media_type": view.by_media_type,
                "text_analysis": analysis_hint(
                    pack_analyses.get(view.entry_id), truncate=True
                ),
                **({"open_review_flag": view.flagged} if include_flagged else {}),
            }
            for view in pack_scope
        ],
        "subfolders": [
            {
                "folder": name,
                "subtree_files": subtree.get((chosen, name), 0),
                **(
                    {"subtree_packs": subtree_packs[(chosen, name)]}
                    if (chosen, name) in subtree_packs
                    else {}
                ),
            }
            for name in sorted(children)
        ],
        "total_files": len(in_scope),
        "truncated": len(in_scope) > limit,
    }


@dataclass
class _UnfiledPack(PackView):
    flagged: bool = False


def _unfiled_packs(
    session: Session, root_id: int | None, include_flagged: bool
) -> list[_UnfiledPack]:
    """Unfiled packs with at least one present member, in folder order."""
    ids = [
        pack_id
        for pack_id in session.exec(
            select(col(Pack.id)).where(col(Pack.disposition) == Disposition.unfiled)
        ).all()
        if pack_id is not None
    ]
    views = pack_views(session, ids)
    flagged = set(
        session.exec(
            select(col(ReviewFlag.entry_id))
            .where(col(ReviewFlag.entry_id).in_([v.entry_id for v in views.values()]))
            .where(col(ReviewFlag.resolved_at).is_(None))
        ).all()
    )
    out = [
        _UnfiledPack(**vars(view), flagged=view.entry_id in flagged)
        for view in views.values()
        if view.members > 0
        and (root_id is None or view.root_id == root_id)
        and (include_flagged or view.entry_id not in flagged)
    ]
    return sorted(out, key=lambda v: (v.root_id, v.folder, v.entry_id))


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
    kept: dict[int, int] = defaultdict(int)
    for statement in (
        select(col(ProductLine.product_type_id), func.count())
        .select_from(File)
        .join(Entry, col(Entry.file_id) == col(File.id))
        .join(Product, col(Product.id) == col(Entry.product_id))
        .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
        .where(col(File.disposition) == Disposition.keep)
        .group_by(col(ProductLine.product_type_id)),
        # Members of kept packs are kept files too.
        select(col(ProductLine.product_type_id), func.count())
        .select_from(File)
        .join(Pack, col(Pack.id) == col(File.pack_id))
        .join(Entry, col(Entry.pack_id) == col(Pack.id))
        .join(Product, col(Product.id) == col(Entry.product_id))
        .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
        .where(col(Pack.disposition) == Disposition.keep)
        .group_by(col(ProductLine.product_type_id)),
    ):
        for type_id, count in session.exec(statement).all():
            kept[type_id] += count
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
