from __future__ import annotations

import fitz
import zxingcpp

from ._pdf_rendering import render_page_image
from .identifiers import PublicationIdentifier, _decode_publication_barcode


def scan_publication_identifiers(
    doc: fitz.Document, pages: set[int]
) -> tuple[PublicationIdentifier, ...]:
    matches: list[PublicationIdentifier] = []
    for page_number in sorted(pages):
        image = render_page_image(doc[page_number])
        for barcode in zxingcpp.read_barcodes(image):
            match = _decode_publication_barcode(barcode.text, page_number)
            if match is not None:
                matches.append(match)
    return tuple(matches)
