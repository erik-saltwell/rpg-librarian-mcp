from __future__ import annotations

import json

import fitz

from .ocr import ocr_page_image
from .pdf_rendering import render_page_image

_BARCODE_SAMPLE_SIZE = 2  # first N pages
_TEXT_SAMPLE_HEAD = 5  # first N pages
_TEXT_SAMPLE_TAIL = 2  # last N pages
_MIN_EXTRACTABLE_TEXT_CHARS = 20


def barcode_sample_pages(page_count: int) -> set[int]:
    """0-indexed pages to scan for a barcode: first two pages plus the last page.

    A `set` means dedup for short documents (1- and 2-page PDFs) falls out
    of the data structure -- no explicit branching per page-count bucket.
    """
    return set(range(min(_BARCODE_SAMPLE_SIZE, page_count))) | {page_count - 1}


def text_sample_pages(page_count: int) -> set[int]:
    """0-indexed pages to sample for text: first five pages plus the last two."""
    return set(range(min(_TEXT_SAMPLE_HEAD, page_count))) | set(
        range(max(0, page_count - _TEXT_SAMPLE_TAIL), page_count)
    )


def _has_extractable_text(page: fitz.Page) -> bool:
    text = str(page.get_text("text"))
    return len(text.strip()) >= _MIN_EXTRACTABLE_TEXT_CHARS


def extract_page_texts(doc: fitz.Document, pages: set[int]) -> dict[int, str]:
    """0-indexed page number -> extracted text, for each page in `pages`.

    Direct text extraction is used where the page has a real text layer;
    otherwise the page is OCR'd.
    """
    page_texts: dict[int, str] = {}
    for page_number in sorted(pages):
        page = doc[page_number]
        if _has_extractable_text(page):
            text = str(page.get_text("text"))
        else:
            text = ocr_page_image(render_page_image(page))
        page_texts[page_number] = text.strip()
    return page_texts


def sample_text_json(page_texts: dict[int, str]) -> str:
    """`{"pages": {"<1-indexed page number>": "<text>", ...}}` for storage.

    Keyed by actual page number (not list position) so gaps between
    first-N and last-N samples are self-evident.
    """
    pages = {str(page_number + 1): text for page_number, text in page_texts.items()}
    return json.dumps({"pages": pages})
