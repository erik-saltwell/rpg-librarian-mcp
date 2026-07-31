import hashlib
from pathlib import Path

import pytest

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.ingest_external_source import ingest_external_source
from rpg_librarian_mcp.model import Entry

FAKE_SHA = "a" * 64


def _library(tmp_path: Path) -> tuple[Catalog, Path]:
    library_root = tmp_path / "library"
    library_root.mkdir()
    return Catalog(library_root=library_root), library_root


def _write_file(root: Path, relative: str, content: str) -> Path:
    file_path = root / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def test_copies_new_files_preserving_structure(tmp_path):
    catalog, library_root = _library(tmp_path)
    source = tmp_path / "friend-drive"
    _write_file(source, "Chaosium/book.pdf", "new content")

    result = ingest_external_source(catalog, source, "dave")

    assert result["scanned"] == 1
    assert result["copied"] == 1
    assert result["skipped_duplicate"] == 0
    copied_file = library_root / "_inbox" / "dave" / "Chaosium" / "book.pdf"
    assert copied_file.read_text() == "new content"
    report_path = library_root / str(result["report_path"])
    assert report_path.exists()
    assert "Chaosium/book.pdf" in report_path.read_text()


def test_skips_files_already_in_the_library_by_hash(tmp_path):
    catalog, library_root = _library(tmp_path)
    _write_file(library_root, "books/shelf/existing.pdf", "duplicate content")
    with session_scope(catalog) as session:
        session.add(
            Entry(
                parent_path=Path("books/shelf"),
                filename="existing.pdf",
                sha256=_sha256_of("duplicate content"),
                size_in_bytes=len("duplicate content"),
                mime_type="application/pdf",
                media_type="pdf",
            )
        )
        session.commit()

    source = tmp_path / "friend-drive"
    _write_file(source, "dupe.pdf", "duplicate content")

    result = ingest_external_source(catalog, source, "dave")

    assert result["copied"] == 0
    assert result["skipped_duplicate"] == 1
    assert not (library_root / "_inbox" / "dave" / "dupe.pdf").exists()
    report_text = (library_root / str(result["report_path"])).read_text()
    assert "books/shelf/existing.pdf" in report_text


def test_second_run_does_not_recopy_already_staged_content(tmp_path):
    catalog, _library_root = _library(tmp_path)
    source = tmp_path / "friend-drive"
    _write_file(source, "book.pdf", "new content")

    first = ingest_external_source(catalog, source, "dave")
    assert first["copied"] == 1

    second = ingest_external_source(catalog, source, "dave")

    assert second["copied"] == 0
    assert second["skipped_duplicate"] == 1


def test_rejects_a_source_inside_the_library_root(tmp_path):
    catalog, library_root = _library(tmp_path)
    inside = library_root / "already-cataloged"
    inside.mkdir()

    with pytest.raises(ValueError, match="inside the library root"):
        ingest_external_source(catalog, inside, "dave")


def test_rejects_a_relative_source_path(tmp_path):
    catalog, _library_root = _library(tmp_path)

    with pytest.raises(ValueError, match="absolute path"):
        ingest_external_source(catalog, Path("relative/dir"), "dave")


def test_rejects_a_name_with_a_path_separator(tmp_path):
    catalog, _library_root = _library(tmp_path)
    source = tmp_path / "friend-drive"
    source.mkdir()

    with pytest.raises(ValueError, match="path separators"):
        ingest_external_source(catalog, source, "dave/nested")


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
