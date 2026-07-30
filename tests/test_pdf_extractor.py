from pathlib import Path
from types import SimpleNamespace

import pytest

from rpg_librarian_mcp.metadata.extractors import pdf_extractor
from rpg_librarian_mcp.metadata.extractors.pdf_extractor import PdfExtractor
from rpg_librarian_mcp.model import PdfMetadata


class _Doc:
    page_count = 3
    is_encrypted = False
    needs_pass = False

    def __init__(self) -> None:
        self.metadata: dict[str, str | None] = {}

    def __getitem__(self, index):
        return SimpleNamespace(get_text=lambda mode: "extractable text " * 2)


def _no_media_info(monkeypatch):
    monkeypatch.setattr(
        pdf_extractor.MediaInfo,
        "parse",
        lambda filename: SimpleNamespace(general_tracks=[]),
    )


def test_extract_custom_metadata_returns_pdf_flags_and_page_signals(monkeypatch):
    _no_media_info(monkeypatch)
    monkeypatch.setattr(pdf_extractor.fitz, "open", lambda file_path: _Doc())

    metadata = PdfExtractor(Path("book.pdf")).extract_custom_metadata()

    assert isinstance(metadata, PdfMetadata)
    assert metadata.page_count == 3
    assert metadata.is_encrypted is False
    assert metadata.needs_password is False
    assert metadata.has_extractable_text is True
    assert metadata.likely_scanned is False


def test_extract_file_metadata_reads_title_and_author_from_pdf_metadata(monkeypatch):
    """Bug 1: pymediainfo never exposes PDF Info-dict/XMP title/author, so
    title/artist must come from fitz's doc.metadata instead."""
    _no_media_info(monkeypatch)
    doc = _Doc()
    doc.metadata = {
        "title": "Temple of Lies",
        "author": "Zzarchov Kowolski",
        "creator": "Adobe InDesign 16.2 (Windows)",
    }
    monkeypatch.setattr(pdf_extractor.fitz, "open", lambda file_path: doc)

    file_metadata = PdfExtractor(Path("book.pdf")).extract_file_metadata()

    assert file_metadata.title == "Temple of Lies"
    assert file_metadata.artist == "Zzarchov Kowolski"


def test_extract_file_metadata_does_not_leak_creator_as_artist(monkeypatch):
    """`creator` is the authoring application, not an author -- it must
    never be used to fill in `artist` when `author` is blank."""
    _no_media_info(monkeypatch)
    doc = _Doc()
    doc.metadata = {
        "title": "interior.indd",
        "author": "",
        "creator": "Adobe InDesign CS (3.0.1)",
    }
    monkeypatch.setattr(pdf_extractor.fitz, "open", lambda file_path: doc)

    file_metadata = PdfExtractor(Path("book.pdf")).extract_file_metadata()

    assert file_metadata.artist is None


def test_is_encrypted_true_for_permission_restricted_pdf_with_no_user_password(
    monkeypatch,
):
    """Bug 2: PyMuPDF auto-authenticates on open when no user password is
    required, resetting `is_encrypted` to False even though the file still
    carries owner-password/permission-restriction encryption. That state
    is only visible via doc.metadata['encryption']."""
    _no_media_info(monkeypatch)
    doc = _Doc()
    doc.is_encrypted = False
    doc.needs_pass = False
    doc.metadata = {"encryption": "Standard V4 R4 128-bit AES"}
    monkeypatch.setattr(pdf_extractor.fitz, "open", lambda file_path: doc)

    metadata = PdfExtractor(Path("book.pdf")).extract_custom_metadata()

    assert isinstance(metadata, PdfMetadata)
    assert metadata.is_encrypted is True
    assert metadata.needs_password is False


def test_unparseable_pdf_raises_instead_of_silently_returning_empty_metadata(
    monkeypatch,
):
    """Bug 3: a corrupted PDF must surface as a failure, not as a
    successfully-processed all-NULL metadata row."""
    _no_media_info(monkeypatch)

    def _raise(file_path):
        raise pdf_extractor.fitz.FileDataError("Failed to open file")

    monkeypatch.setattr(pdf_extractor.fitz, "open", _raise)

    with pytest.raises(pdf_extractor.fitz.FileDataError):
        PdfExtractor(Path("garbage.pdf"))
