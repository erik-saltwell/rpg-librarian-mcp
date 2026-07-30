from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import litellm
import pytest
from sqlmodel import select

from conftest import insert_raw_entry
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands import ReadPdfsCommand as read_pdfs_module
from rpg_librarian_mcp.commands.ReadPdfsCommand import ReadPdfsCommand
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, Error, PdfContents, ProcessingStage
from rpg_librarian_mcp.tools import text_extraction


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _insert_pdf_entry(catalog: Catalog, filename: str = "book.pdf") -> None:
    insert_raw_entry(
        catalog,
        parent_path="shelf/box",
        filename=filename,
        media_type="pdf",
        mime_type="application/pdf",
    )


async def _catalog_text_file(tmp_path: Path, filename: str) -> None:
    """A real, non-PDF cataloged file -- sniffed and stored as media_type=text."""
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True, exist_ok=True)
    (shelf / filename).write_text("hello world")
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(tmp_path, True, False, AsyncMock())


def _get_entry(catalog: Catalog, filename: str) -> Entry:
    with session_scope(catalog) as session:
        return session.exec(select(Entry).where(Entry.filename == filename)).one()


class _Doc:
    needs_pass = False

    def __init__(self, page_count: int = 1) -> None:
        self.page_count = page_count
        self.closed = False

    def __getitem__(self, index):
        return SimpleNamespace(get_text=lambda mode: "some real extractable text " * 2)

    def close(self) -> None:
        self.closed = True


class _EmptyDoc(_Doc):
    def __getitem__(self, index):
        return SimpleNamespace(get_text=lambda mode: "")


def _command(catalog: Catalog) -> ReadPdfsCommand:
    return ReadPdfsCommand(catalog, ProcessingStage.read_pdfs)


def _no_tesseract_check(monkeypatch) -> None:
    monkeypatch.setattr(read_pdfs_module, "check_tesseract_available", lambda: None)


def _no_barcode_match(monkeypatch) -> None:
    monkeypatch.setattr(
        read_pdfs_module, "find_isbn_or_issn_barcode", lambda doc, pages: None
    )


def _no_llm_call(monkeypatch) -> None:
    """Content is real text, so process_one would call the LLM unless stubbed."""
    monkeypatch.setattr(
        read_pdfs_module,
        "judge_pdf_contents",
        lambda sample_text: SimpleNamespace(description=None, possible_system=None),
    )


async def test_should_process_is_false_for_non_pdf_entries(tmp_path):
    await _catalog_text_file(tmp_path, "book.txt")
    catalog = _catalog(tmp_path)
    entry = _get_entry(catalog, "book.txt")
    command = _command(catalog)

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is False


async def test_should_process_is_true_when_no_pdfcontents_exists(tmp_path):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    command = _command(catalog)

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


async def test_should_process_is_false_once_pdfcontents_exists_with_no_error(tmp_path):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    command = _command(catalog)

    with session_scope(catalog) as session:
        session.add(PdfContents(entry_id=entry.id))
        session.commit()

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is False


async def test_should_process_is_true_again_when_an_error_row_exists(tmp_path):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    command = _command(catalog)

    with session_scope(catalog) as session:
        session.add(PdfContents(entry_id=entry.id))
        session.add(
            Error(
                entry_id=entry.id,
                stage=ProcessingStage.read_pdfs,
                error_text="stale failure",
            )
        )
        session.commit()

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


async def test_password_protected_pdf_is_skipped_not_erroed(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    _no_tesseract_check(monkeypatch)
    doc = _Doc()
    doc.needs_pass = True
    monkeypatch.setattr(read_pdfs_module.fitz, "open", lambda file_path: doc)
    command = _command(catalog)

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.succeeded == 1
    assert result.errored == 0
    assert doc.closed is True
    with session_scope(catalog) as session:
        assert session.exec(select(PdfContents)).all() == []


async def test_process_one_persists_barcode_match_and_sample_text(
    tmp_path, monkeypatch
):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    _no_tesseract_check(monkeypatch)
    _no_llm_call(monkeypatch)
    monkeypatch.setattr(read_pdfs_module.fitz, "open", lambda file_path: _Doc())
    monkeypatch.setattr(
        read_pdfs_module,
        "find_isbn_or_issn_barcode",
        lambda doc, pages: SimpleNamespace(
            barcode_text="9780306406157", isbn="9780306406157", issn=None
        ),
    )
    command = _command(catalog)

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.succeeded == 1
    assert result.errored == 0
    with session_scope(catalog) as session:
        contents = session.get(PdfContents, entry.id)
        assert contents is not None
        assert contents.barcode == "9780306406157"
        assert contents.isbn == "9780306406157"
        assert contents.issn is None
        assert contents.sample_text is not None
        assert "pages" in contents.sample_text


async def test_process_one_skips_llm_when_sample_text_is_empty(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    _no_tesseract_check(monkeypatch)
    _no_barcode_match(monkeypatch)
    monkeypatch.setattr(read_pdfs_module.fitz, "open", lambda file_path: _EmptyDoc())
    monkeypatch.setattr(text_extraction, "render_page_image", lambda page: "image")
    monkeypatch.setattr(text_extraction, "ocr_page_image", lambda image: "")

    def _fail_if_called(sample_text):
        raise AssertionError("LLM must not be called when sample text is empty")

    monkeypatch.setattr(read_pdfs_module, "judge_pdf_contents", _fail_if_called)
    monkeypatch.setattr(
        read_pdfs_module.PdfExtractor, "__init__", lambda self, file_path: None
    )
    monkeypatch.setattr(
        read_pdfs_module.PdfExtractor, "extract_isbn", lambda self: None
    )
    monkeypatch.setattr(
        read_pdfs_module.PdfExtractor, "extract_issn", lambda self: None
    )
    command = _command(catalog)

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        contents = session.get(PdfContents, entry.id)
        assert contents is not None
        assert contents.description is None
        assert contents.possible_system is None


async def test_tesseract_missing_aborts_before_any_entry_is_processed(
    tmp_path, monkeypatch
):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)

    def _raise():
        raise RuntimeError("tesseract not found")

    monkeypatch.setattr(read_pdfs_module, "check_tesseract_available", _raise)

    def _fail_if_opened(file_path):
        raise AssertionError("must not open any PDF before the Tesseract check")

    monkeypatch.setattr(read_pdfs_module.fitz, "open", _fail_if_opened)
    command = _command(catalog)

    with pytest.raises(RuntimeError, match="tesseract not found"):
        await command.process(tmp_path, True, False, AsyncMock())


async def test_authentication_error_aborts_the_whole_run(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    _no_tesseract_check(monkeypatch)
    monkeypatch.setattr(read_pdfs_module.fitz, "open", lambda file_path: _Doc())
    monkeypatch.setattr(
        read_pdfs_module,
        "find_isbn_or_issn_barcode",
        lambda doc, pages: SimpleNamespace(
            barcode_text="9780306406157", isbn="9780306406157", issn=None
        ),
    )

    def _raise_auth_error(sample_text):
        raise litellm.AuthenticationError(
            message="bad key", llm_provider="openai", model="gpt-4o-mini"
        )

    monkeypatch.setattr(read_pdfs_module, "judge_pdf_contents", _raise_auth_error)
    command = _command(catalog)

    with pytest.raises(litellm.AuthenticationError):
        await command.process(tmp_path, True, False, AsyncMock())

    with session_scope(catalog) as session:
        assert session.exec(select(Error)).all() == []


async def test_non_fatal_llm_error_still_persists_non_llm_signal(tmp_path, monkeypatch):
    """Bug: a non-fatal LLM failure (e.g. missing credentials) discarded the
    already-extracted barcode/ISBN/sample-text along with the failed
    description/possible_system, instead of persisting what succeeded."""
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    _no_tesseract_check(monkeypatch)
    monkeypatch.setattr(read_pdfs_module.fitz, "open", lambda file_path: _Doc())
    monkeypatch.setattr(
        read_pdfs_module,
        "find_isbn_or_issn_barcode",
        lambda doc, pages: SimpleNamespace(
            barcode_text="9780306406157", isbn="9780306406157", issn=None
        ),
    )

    def _raise(sample_text):
        raise TimeoutError("model took too long")

    monkeypatch.setattr(read_pdfs_module, "judge_pdf_contents", _raise)
    command = _command(catalog)

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.errored == 1
    with session_scope(catalog) as session:
        contents = session.get(PdfContents, entry.id)
        assert contents is not None
        assert contents.barcode == "9780306406157"
        assert contents.isbn == "9780306406157"
        assert contents.sample_text is not None
        assert contents.description is None
        assert contents.possible_system is None


async def test_non_fatal_llm_error_is_recorded_per_entry(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    _insert_pdf_entry(catalog)
    entry = _get_entry(catalog, "book.pdf")
    _no_tesseract_check(monkeypatch)
    monkeypatch.setattr(read_pdfs_module.fitz, "open", lambda file_path: _Doc())
    monkeypatch.setattr(
        read_pdfs_module,
        "find_isbn_or_issn_barcode",
        lambda doc, pages: SimpleNamespace(
            barcode_text="9780306406157", isbn="9780306406157", issn=None
        ),
    )

    def _raise(sample_text):
        raise TimeoutError("model took too long")

    monkeypatch.setattr(read_pdfs_module, "judge_pdf_contents", _raise)
    command = _command(catalog)

    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.errored == 1
    with session_scope(catalog) as session:
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].entry_id == entry.id
        assert errors[0].stage == ProcessingStage.read_pdfs
