import json
from typing import cast

import fitz

from rpg_librarian_mcp.tools import text_extraction
from rpg_librarian_mcp.tools.text_extraction import (
    barcode_sample_pages,
    extract_page_texts,
    sample_text_json,
    text_sample_pages,
)


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self, mode: str) -> str:
        return self._text


class _Doc:
    def __init__(self, texts: dict[int, str]) -> None:
        self._texts = texts

    def __getitem__(self, index: int) -> _Page:
        return _Page(self._texts[index])


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
