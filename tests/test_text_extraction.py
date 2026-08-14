import json
from pathlib import Path
from typing import cast

import fitz

from rpg_librarian_mcp.tools import text_extraction
from rpg_librarian_mcp.tools.text_extraction import (
    barcode_sample_pages,
    extract_page_texts,
    is_likely_image_only,
    is_likely_image_only_isolated,
    sample_text_json,
    text_sample_pages,
)


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self, mode: str) -> str:
        return self._text


class _Doc:
    def __init__(
        self, texts: dict[int, str], page_count: int | None = None, needs_pass=False
    ) -> None:
        self._texts = texts
        self.page_count = page_count if page_count is not None else len(texts)
        self.needs_pass = needs_pass
        self.closed = False

    def __getitem__(self, index: int) -> _Page:
        return _Page(self._texts[index])

    def close(self) -> None:
        self.closed = True


def _fail_if_called(*args, **kwargs):
    raise AssertionError("must not render/OCR when not a single-page candidate")


def test_barcode_sample_pages_dedups_on_short_documents():
    assert barcode_sample_pages(1) == {0}
    assert barcode_sample_pages(2) == {0, 1}
    assert barcode_sample_pages(3) == {0, 1, 2}


def test_barcode_sample_pages_first_two_and_last_on_long_documents():
    assert barcode_sample_pages(10) == {0, 1, 9}


def test_text_sample_pages_dedups_on_short_documents():
    assert text_sample_pages(1) == {0}
    assert text_sample_pages(3) == {0, 1, 2}


def test_text_sample_pages_first_five_and_last_two_on_long_documents():
    assert text_sample_pages(10) == {0, 1, 2, 3, 4, 8, 9}


def test_extract_page_texts_uses_direct_extraction_when_available():
    long_text = "a real text layer " * 3
    doc = cast(fitz.Document, _Doc({0: long_text}))

    page_texts = extract_page_texts(doc, {0})

    assert page_texts[0] == long_text.strip()


def test_extract_page_texts_falls_back_to_ocr_when_no_text_layer(monkeypatch):
    doc = cast(fitz.Document, _Doc({0: ""}))
    monkeypatch.setattr(text_extraction, "render_page_image", lambda page: "fake-image")
    monkeypatch.setattr(text_extraction, "ocr_page_image", lambda image: "ocr'd text")

    page_texts = extract_page_texts(doc, {0})

    assert page_texts[0] == "ocr'd text"


def test_sample_text_json_keys_by_one_indexed_page_number():
    result = sample_text_json({0: "first", 9: "last"})

    assert json.loads(result) == {"pages": {"1": "first", "10": "last"}}


def test_is_likely_image_only_is_false_for_multi_page_docs(monkeypatch):
    doc = cast(fitz.Document, _Doc({0: ""}, page_count=2))
    monkeypatch.setattr(text_extraction, "render_page_image", _fail_if_called)
    monkeypatch.setattr(text_extraction, "ocr_page_image", _fail_if_called)

    assert is_likely_image_only(doc) is False


def test_is_likely_image_only_is_false_when_page_has_a_text_layer(monkeypatch):
    doc = cast(fitz.Document, _Doc({0: "a real text layer " * 3}, page_count=1))
    monkeypatch.setattr(text_extraction, "render_page_image", _fail_if_called)
    monkeypatch.setattr(text_extraction, "ocr_page_image", _fail_if_called)

    assert is_likely_image_only(doc) is False


def test_is_likely_image_only_is_true_when_ocr_finds_negligible_text(monkeypatch):
    doc = cast(fitz.Document, _Doc({0: ""}, page_count=1))
    monkeypatch.setattr(
        text_extraction, "render_page_image", lambda page, dpi: "fake-image"
    )
    monkeypatch.setattr(text_extraction, "ocr_page_image", lambda image: "a b c")

    assert is_likely_image_only(doc) is True


def test_is_likely_image_only_is_false_when_ocr_finds_real_content(monkeypatch):
    doc = cast(fitz.Document, _Doc({0: ""}, page_count=1))
    monkeypatch.setattr(
        text_extraction, "render_page_image", lambda page, dpi: "fake-image"
    )
    monkeypatch.setattr(
        text_extraction, "ocr_page_image", lambda image: " ".join(["word"] * 30)
    )

    assert is_likely_image_only(doc) is False


def test_is_likely_image_only_isolated_opens_and_closes_the_file(monkeypatch):
    doc = _Doc({0: ""}, page_count=1)
    monkeypatch.setattr(text_extraction.fitz, "open", lambda file_path: doc)
    monkeypatch.setattr(
        text_extraction, "render_page_image", lambda page, dpi: "fake-image"
    )
    monkeypatch.setattr(text_extraction, "ocr_page_image", lambda image: "")

    result = is_likely_image_only_isolated(Path("book.pdf"))

    assert result is True
    assert doc.closed is True


def test_is_likely_image_only_isolated_is_false_for_password_protected_pdfs(
    monkeypatch,
):
    doc = _Doc({0: ""}, page_count=1, needs_pass=True)
    monkeypatch.setattr(text_extraction.fitz, "open", lambda file_path: doc)
    monkeypatch.setattr(text_extraction, "render_page_image", _fail_if_called)
    monkeypatch.setattr(text_extraction, "ocr_page_image", _fail_if_called)

    assert is_likely_image_only_isolated(Path("book.pdf")) is False
