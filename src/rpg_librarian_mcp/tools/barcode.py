from __future__ import annotations

from dataclasses import dataclass

import fitz
import zxingcpp

from ..isbn import isbn, issn
from .pdf_rendering import render_page_image


@dataclass(frozen=True, slots=True)
class BarcodeMatch:
    """A decoded barcode that resolved to an ISBN or ISSN."""

    barcode_text: str
    isbn: str | None
    issn: str | None


def find_isbn_or_issn_barcode(
    doc: fitz.Document, pages: set[int]
) -> BarcodeMatch | None:
    """Scan `pages` (0-indexed, in ascending order) for a barcode that decodes
    to an ISBN or ISSN.

    Book/magazine barcodes are conventionally EAN-13 (Bookland), so each
    decoded barcode is tried as an EAN-13-encoded ISBN/ISSN first, falling
    back to treating the raw decoded text itself as an ISBN/ISSN. Returns the
    first match found, in page order.
    """
    for page_number in sorted(pages):
        image = render_page_image(doc[page_number])
        for barcode in zxingcpp.read_barcodes(image):
            match = _resolve(barcode.text)
            if match is not None:
                return match
    return None


def _resolve(text: str) -> BarcodeMatch | None:
    if (from_ean13 := isbn.from_ean13(text)) is not None:
        return BarcodeMatch(barcode_text=text, isbn=from_ean13, issn=None)
    if (from_ean13 := issn.from_ean13(text)) is not None:
        return BarcodeMatch(barcode_text=text, isbn=None, issn=from_ean13)
    if isbn.validate(text):
        return BarcodeMatch(barcode_text=text, isbn=text, issn=None)
    if issn.validate(text):
        return BarcodeMatch(barcode_text=text, isbn=None, issn=text)
    return None
