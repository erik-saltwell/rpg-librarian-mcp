from pathlib import Path
from typing import Any, cast

import pytest
from sqlmodel import select

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.entry_details import get_entry_details as _get_entry_details
from rpg_librarian_mcp.model import (
    Entry,
    Error,
    FileMetadata,
    IdentificationMethod,
    PdfContents,
    PdfMetadata,
    ProcessingStage,
    Product,
    ReviewFlag,
)

JsonDict = dict[str, Any]


def get_entry_details(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _get_entry_details(*args, **kwargs))


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _write_file(tmp_path: Path, relative: str, content: str = "x") -> Path:
    file_path = tmp_path / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def _make_entry(session, parent_path: str, filename: str, product=None) -> Entry:
    entry = Entry(
        parent_path=Path(parent_path),
        filename=filename,
        sha256="a" * 64,
        size_in_bytes=10,
        mime_type="application/pdf",
        media_type="pdf",
        product_id=product.id if product is not None else None,
    )
    session.add(entry)
    session.flush()
    return entry


def test_raises_when_not_cataloged(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.pdf")

    with pytest.raises(ValueError, match="not cataloged"):
        get_entry_details(catalog, tmp_path / "shelf" / "box" / "book.pdf")


def test_bare_entry_has_no_product_and_empty_related_rows(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.pdf")
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "book.pdf")
        session.commit()

    result = get_entry_details(catalog, tmp_path / "shelf" / "box" / "book.pdf")

    assert result["path"] == "shelf/box/book.pdf"
    assert result["product"] is None
    assert result["errors"] == []
    assert result["review_flags"] == []
    assert result["metadata"] == {}


def test_includes_linked_product(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.pdf")
    with session_scope(catalog) as session:
        product = Product(
            title="Keeper Rulebook", identification_method=IdentificationMethod.manual
        )
        session.add(product)
        session.flush()
        _make_entry(session, "shelf/box", "book.pdf", product=product)
        session.commit()

    result = get_entry_details(catalog, tmp_path / "shelf" / "box" / "book.pdf")

    assert result["product"]["title"] == "Keeper Rulebook"


def test_includes_errors_review_flags_and_metadata_tables(tmp_path):
    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.pdf")
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "book.pdf")
        session.add(
            Error(
                entry_id=entry.id,
                stage=ProcessingStage.read_pdfs,
                error_text="boom",
            )
        )
        session.add(ReviewFlag(entry_id=entry.id, reason="unsure which edition"))
        session.add(FileMetadata(entry_id=entry.id, title="Embedded Title"))
        session.add(PdfMetadata(entry_id=entry.id, page_count=42))
        session.add(PdfContents(entry_id=entry.id, sample_text="keeper text"))
        session.commit()

    result = get_entry_details(catalog, tmp_path / "shelf" / "box" / "book.pdf")

    assert len(result["errors"]) == 1
    assert result["errors"][0]["error_text"] == "boom"
    assert len(result["review_flags"]) == 1
    assert result["review_flags"][0]["reason"] == "unsure which edition"
    assert result["metadata"]["file_metadata"]["title"] == "Embedded Title"
    assert result["metadata"]["pdf_metadata"]["page_count"] == 42
    assert result["metadata"]["pdf_contents"]["sample_text"] == "keeper text"
    assert "image_metadata" not in result["metadata"]


def test_result_is_json_serializable(tmp_path):
    """model_dump(mode='json') must actually strip datetimes/UUIDs down to
    JSON-safe primitives, not leave them for the caller to trip over."""
    import json

    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.pdf")
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "book.pdf")
        session.add(ReviewFlag(entry_id=entry.id, reason="check this"))
        session.commit()

    result = get_entry_details(catalog, tmp_path / "shelf" / "box" / "book.pdf")

    json.dumps(result)  # raises if anything isn't JSON-serializable


def test_both_open_and_resolved_review_flags_are_included(tmp_path):
    from rpg_librarian_mcp.model.core import utc_now

    catalog = _catalog(tmp_path)
    _write_file(tmp_path, "shelf/box/book.pdf")
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "book.pdf")
        session.add(
            ReviewFlag(
                entry_id=entry.id,
                reason="old, already resolved",
                resolved_at=utc_now(),
                resolution_note="handled",
            )
        )
        session.commit()

    with session_scope(catalog) as session:
        entry = session.exec(select(Entry).where(Entry.filename == "book.pdf")).one()
        session.add(ReviewFlag(entry_id=entry.id, reason="new, still open"))
        session.commit()

    result = get_entry_details(catalog, tmp_path / "shelf" / "box" / "book.pdf")

    reasons = {flag["reason"] for flag in result["review_flags"]}
    assert reasons == {"old, already resolved", "new, still open"}
