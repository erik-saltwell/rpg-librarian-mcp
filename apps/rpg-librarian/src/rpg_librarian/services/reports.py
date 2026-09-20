"""Structured summaries of one file, product, or product line.

Reports carry the text-analysis *hint* (a description and a system guess) but never the
sampled page text: a model already read the sample, and re-sending it costs context for
no new signal. Each report also carries `pending_changes`, so the session can tell the
user when to run `reorganize`.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, SQLModel, col, select

from ..errors import UsageError
from ..model import (
    AudioMetadata,
    Disposition,
    DtrpgResult,
    Error,
    File,
    FileMetadata,
    FileText,
    FileTextAnalysis,
    GoogleSearchResult,
    ImageMetadata,
    IsbnResult,
    MeshMetadata,
    PdfMetadata,
    Product,
    ProductLine,
    ProductLineAlias,
    ProductType,
    ReviewFlag,
    Root,
    RpggeekResult,
    VideoMetadata,
)
from ..paths import kept_file_count, sanitize_name
from .names import normalize_name
from .pending import pending_changes

_BOOKKEEPING = {"file_id", "created_at", "updated_at"}
_MEDIA_TABLES: dict[str, type[SQLModel]] = {
    "pdf": PdfMetadata,
    "image": ImageMetadata,
    "audio": AudioMetadata,
    "video": VideoMetadata,
    "mesh": MeshMetadata,
}
_EVIDENCE_TABLES: dict[str, type[Any]] = {
    "isbn": IsbnResult,
    "dtrpg": DtrpgResult,
    "rpggeek": RpggeekResult,
    "google": GoogleSearchResult,
}
_HINT_DESCRIPTION_CHARS = 300


def _row(
    row: SQLModel | None, *, drop: set[str] = _BOOKKEEPING
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: v for k, v in row.model_dump().items() if k not in drop}


def analysis_hint(
    analysis: FileTextAnalysis | None, *, truncate: bool
) -> dict[str, Any] | None:
    """The text-analysis hint for a file, or None when it has none."""
    if analysis is None:
        return None
    description = analysis.description
    if truncate and description and len(description) > _HINT_DESCRIPTION_CHARS:
        description = description[:_HINT_DESCRIPTION_CHARS].rstrip() + "..."
    return {"description": description, "possible_system": analysis.possible_system}


def product_ref(session: Session, product_id: int | None) -> dict[str, Any] | None:
    """A product with its line and type, as small references."""
    if product_id is None:
        return None
    row = session.exec(
        select(Product, ProductLine, ProductType)
        .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
        .join(ProductType, col(ProductType.id) == col(ProductLine.product_type_id))
        .where(col(Product.id) == product_id)
    ).first()
    if row is None:
        return None
    product, line, product_type = row
    return {
        "id": product.id,
        "name": product.name,
        "line": {"id": line.id, "name": line.name},
        "type": {"id": product_type.id, "name": product_type.name},
    }


def target_folder(session: Session, product_id: int) -> str | None:
    """The folder a product's kept files go in, given how many it has now."""
    ref = product_ref(session, product_id)
    if ref is None:
        return None
    parts = [sanitize_name(ref["type"]["name"]), sanitize_name(ref["line"]["name"])]
    if kept_file_count(session, product_id) > 1:
        parts.append(sanitize_name(ref["name"]))
    return "/".join(parts)


def report_file(session: Session, file_id: int) -> dict[str, Any]:
    file = session.get(File, file_id)
    if file is None:
        raise UsageError(f"No file with id {file_id}.")
    root = session.get(Root, file.root_id)
    assert root is not None
    folder, _, filename = file.relative_path.rpartition("/")

    media: dict[str, Any] = {}
    for kind, table in _MEDIA_TABLES.items():
        row = _row(session.get(table, file_id))
        if row is not None:
            media[kind] = row

    text = session.get(FileText, file_id)
    open_flag = session.exec(
        select(ReviewFlag)
        .where(col(ReviewFlag.file_id) == file_id)
        .where(col(ReviewFlag.resolved_at).is_(None))
    ).first()
    original = session.get(File, file.duplicate_of_id) if file.duplicate_of_id else None
    copies = session.exec(
        select(col(File.id)).where(col(File.duplicate_of_id) == file_id)
    ).all()

    return {
        "file": {
            "id": file.id,
            "root": {"id": root.id, "kind": root.kind.value, "path": root.path},
            "relative_path": file.relative_path,
            "folder": folder,
            "filename": filename,
            "size_bytes": file.size_bytes,
            "mime_type": file.mime_type,
            "media_type": file.media_type.value if file.media_type else None,
            "sha256": file.sha256,
            "disposition": file.disposition.value,
            "missing_since": file.missing_since,
            "last_seen_at": file.last_seen_at,
        },
        "product": product_ref(session, file.product_id),
        "duplicate_of": (
            {"id": original.id, "relative_path": original.relative_path}
            if original
            else None
        ),
        "duplicate_ids": list(copies),
        "embedded_metadata": _row(session.get(FileMetadata, file_id)),
        "media_metadata": media,
        "identifiers": (
            {
                "isbn": text.isbn,
                "issn": text.issn,
                "barcode": text.barcode,
                "pages_sampled": len(text.sample_pages or {}),
            }
            if text
            else None
        ),
        "text_analysis": analysis_hint(
            session.get(FileTextAnalysis, file_id), truncate=False
        ),
        "evidence": {
            name: _row(session.get(table, file_id))
            for name, table in _EVIDENCE_TABLES.items()
        },
        "errors": [
            {"stage": e.stage.value, "error": e.error_text, "at": e.occurred_at}
            for e in session.exec(
                select(Error).where(col(Error.file_id) == file_id)
            ).all()
        ],
        "review_flag": (
            {"reason": open_flag.reason, "opened_at": open_flag.created_at}
            if open_flag
            else None
        ),
        "pending_changes": pending_changes(session),
    }


def _files_summary(session: Session, product_id: int) -> list[dict[str, Any]]:
    rows = session.exec(
        select(File, FileTextAnalysis)
        .join(
            FileTextAnalysis,
            col(FileTextAnalysis.file_id) == col(File.id),
            isouter=True,
        )
        .where(col(File.product_id) == product_id)
        .order_by(col(File.relative_path))
    ).all()
    return [
        {
            "id": file.id,
            "root_id": file.root_id,
            "relative_path": file.relative_path,
            "media_type": file.media_type.value if file.media_type else None,
            "size_bytes": file.size_bytes,
            "disposition": file.disposition.value,
            "text_analysis": analysis_hint(analysis, truncate=True),
        }
        for file, analysis in rows
    ]


def report_product(
    session: Session,
    *,
    product_id: int | None = None,
    product_type: str | None = None,
    product_line: str | None = None,
    product: str | None = None,
) -> dict[str, Any]:
    """Identify by `product_id`, or by type, line, and name together."""
    if product_id is None:
        if not (product_type and product_line and product):
            raise UsageError(
                "Give product_id, or product_type, product_line, and product together."
            )
        line = _find_line(session, product_type, product_line)
        assert line.id is not None
        wanted = normalize_name(product)
        match = next(
            (
                p
                for p in session.exec(
                    select(Product).where(col(Product.product_line_id) == line.id)
                ).all()
                if normalize_name(p.name) == wanted
            ),
            None,
        )
        if match is None:
            raise UsageError(f"No product {product!r} in line {line.name!r}.")
        product_id = match.id
    row = session.get(Product, product_id)
    if row is None:
        raise UsageError(f"No product with id {product_id}.")
    assert row.id is not None

    ref = product_ref(session, row.id)
    assert ref is not None
    files = _files_summary(session, row.id)
    by_disposition: dict[str, int] = {}
    for item in files:
        by_disposition[item["disposition"]] = (
            by_disposition.get(item["disposition"], 0) + 1
        )
    return {
        "product": {
            **(_row(row, drop=_BOOKKEEPING | {"product_line_id"}) or {}),
            "line": ref["line"],
            "type": ref["type"],
        },
        "files": files,
        "files_by_disposition": by_disposition,
        "target_folder": target_folder(session, row.id),
        "pending_changes": pending_changes(session),
    }


def _find_line(session: Session, product_type: str, name: str) -> ProductLine:
    types = session.exec(select(ProductType)).all()
    wanted_type = normalize_name(product_type)
    found_type = next((t for t in types if normalize_name(t.name) == wanted_type), None)
    if found_type is None:
        raise UsageError(
            f"No product type {product_type!r}. Types: {[t.name for t in types]}."
        )
    wanted = normalize_name(name)
    lines = session.exec(
        select(ProductLine).where(col(ProductLine.product_type_id) == found_type.id)
    ).all()
    aliases = session.exec(select(ProductLineAlias)).all()
    for line in lines:
        names = {normalize_name(line.name)} | {
            normalize_name(a.alias) for a in aliases if a.product_line_id == line.id
        }
        if wanted in names:
            return line
    raise UsageError(
        f"No product line {name!r} under type {found_type.name!r}. "
        "Try list_product_lines with a search."
    )


def report_line(
    session: Session,
    *,
    line_id: int | None = None,
    product_type: str | None = None,
    product_line: str | None = None,
) -> dict[str, Any]:
    """Identify by `line_id`, or by type and name (or alias) together."""
    if line_id is not None:
        line = session.get(ProductLine, line_id)
        if line is None:
            raise UsageError(f"No product line with id {line_id}.")
    else:
        if not (product_type and product_line):
            raise UsageError("Give line_id, or product_type and product_line together.")
        line = _find_line(session, product_type, product_line)
    assert line.id is not None
    product_type_row = session.get(ProductType, line.product_type_id)
    assert product_type_row is not None

    products = []
    for product in session.exec(
        select(Product)
        .where(col(Product.product_line_id) == line.id)
        .order_by(col(Product.name))
    ).all():
        assert product.id is not None
        counts = session.exec(
            select(col(File.disposition)).where(col(File.product_id) == product.id)
        ).all()
        products.append(
            {
                "id": product.id,
                "name": product.name,
                "publisher": product.publisher,
                "year": product.year,
                "files": len(counts),
                "kept_files": sum(1 for d in counts if d is Disposition.keep),
            }
        )
    return {
        "line": {
            "id": line.id,
            "name": line.name,
            "type": {"id": product_type_row.id, "name": product_type_row.name},
            "aliases": sorted(
                a.alias
                for a in session.exec(
                    select(ProductLineAlias).where(
                        col(ProductLineAlias.product_line_id) == line.id
                    )
                ).all()
            ),
        },
        "products": products,
        "pending_changes": pending_changes(session),
    }
