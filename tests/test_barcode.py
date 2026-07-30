from types import SimpleNamespace
from typing import cast

import fitz

from rpg_librarian_mcp.tools import barcode


class _Doc:
    def __init__(self, pages: dict[int, str]) -> None:
        self._pages = pages

    def __getitem__(self, index: int):
        return self._pages[index]


def _doc(pages: dict[int, str]) -> fitz.Document:
    return cast(fitz.Document, _Doc(pages))


def _fake_render(monkeypatch, images_by_page: dict) -> None:
    monkeypatch.setattr(barcode, "render_page_image", lambda page: images_by_page[page])


def _fake_read_barcodes(monkeypatch, barcodes_by_image: dict) -> None:
    monkeypatch.setattr(
        barcode.zxingcpp,
        "read_barcodes",
        lambda image: [SimpleNamespace(text=t) for t in barcodes_by_image[image]],
    )


def test_finds_isbn_from_ean13_barcode(monkeypatch):
    doc = _doc({0: "page0"})
    _fake_render(monkeypatch, {"page0": "image0"})
    # A real Bookland EAN-13 for ISBN-13 9780306406157
    _fake_read_barcodes(monkeypatch, {"image0": ["9780306406157"]})

    match = barcode.find_isbn_or_issn_barcode(doc, {0})

    assert match is not None
    assert match.barcode_text == "9780306406157"
    assert match.isbn == "9780306406157"
    assert match.issn is None


def test_finds_issn_from_977_prefixed_ean13_barcode(monkeypatch):
    doc = _doc({0: "page0"})
    _fake_render(monkeypatch, {"page0": "image0"})
    _fake_read_barcodes(monkeypatch, {"image0": ["9772049363002"]})

    match = barcode.find_isbn_or_issn_barcode(doc, {0})

    assert match is not None
    assert match.isbn is None
    assert match.issn == "20493630"


def test_falls_back_to_raw_isbn_validation_when_not_ean13(monkeypatch):
    doc = _doc({0: "page0"})
    _fake_render(monkeypatch, {"page0": "image0"})
    _fake_read_barcodes(monkeypatch, {"image0": ["0306406152"]})

    match = barcode.find_isbn_or_issn_barcode(doc, {0})

    assert match is not None
    assert match.isbn == "0306406152"


def test_returns_none_when_no_barcode_resolves(monkeypatch):
    doc = _doc({0: "page0"})
    _fake_render(monkeypatch, {"page0": "image0"})
    _fake_read_barcodes(monkeypatch, {"image0": ["not-a-barcode"]})

    assert barcode.find_isbn_or_issn_barcode(doc, {0}) is None


def test_scans_pages_in_ascending_order_and_stops_at_first_match(monkeypatch):
    doc = _doc({0: "page0", 1: "page1"})
    _fake_render(monkeypatch, {"page0": "image0", "page1": "image1"})
    _fake_read_barcodes(
        monkeypatch,
        {"image0": ["9780306406157"], "image1": ["9780132350884"]},
    )

    match = barcode.find_isbn_or_issn_barcode(doc, {1, 0})

    assert match is not None
    assert match.isbn == "9780306406157"
