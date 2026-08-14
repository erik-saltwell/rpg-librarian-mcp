from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import fitz

from ..observability import log_entry_fields
from .ocr import ocr_page_image
from .pdf_rendering import render_page_image

_BARCODE_SAMPLE_SIZE = 2  # first N pages
_TEXT_SAMPLE_HEAD = 5  # first N pages
_TEXT_SAMPLE_TAIL = 2  # last N pages
_MIN_EXTRACTABLE_TEXT_CHARS = 20

# Chosen from OCR'ing 40 known-map and 40 non-map single-page PDFs at
# 100 DPI: word counts cluster below ~22 for real maps and below ~22 for
# other low-text single-page images (dungeon tiles, character-sheet
# stubs, art), then both groups jump past 33 -- any threshold in that gap
# separates "negligible legible text" from "has real content" equally
# well for both.
_IMAGE_ONLY_OCR_DPI = 100
_IMAGE_ONLY_WORD_THRESHOLD = 25


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


class PageTextResult(NamedTuple):
    page_texts: dict[int, str]
    pages_sampled: int
    pages_direct_extraction: int
    pages_ocr: int


def _extract_page_texts_with_counts(
    doc: fitz.Document, pages: set[int]
) -> PageTextResult:
    page_texts: dict[int, str] = {}
    direct_pages = 0
    ocr_pages = 0
    for page_number in sorted(pages):
        page = doc[page_number]
        if _has_extractable_text(page):
            text = str(page.get_text("text"))
            direct_pages += 1
        else:
            text = ocr_page_image(render_page_image(page))
            ocr_pages += 1
        page_texts[page_number] = text.strip()

    return PageTextResult(
        page_texts=page_texts,
        pages_sampled=len(pages),
        pages_direct_extraction=direct_pages,
        pages_ocr=ocr_pages,
    )


def extract_page_texts(doc: fitz.Document, pages: set[int]) -> dict[int, str]:
    """0-indexed page number -> extracted text, for each page in `pages`.

    Direct text extraction is used where the page has a real text layer;
    otherwise the page is OCR'd. Reports how many pages were sampled and
    the direct-extraction/OCR split via `log_entry_fields` -- a no-op
    outside of a tracked entry.
    """
    result = _extract_page_texts_with_counts(doc, pages)
    log_entry_fields(
        pages_sampled=result.pages_sampled,
        pages_direct_extraction=result.pages_direct_extraction,
        pages_ocr=result.pages_ocr,
    )
    return result.page_texts


def extract_page_texts_isolated(file_path: Path, pages: set[int]) -> PageTextResult:
    """Same page-render-or-OCR work as `extract_page_texts`, but opens
    `file_path` itself and is meant to be run through `WorkerPool.submit`
    -- the actual risky calls (PyMuPDF rendering, tesseract via
    pytesseract) happen in a worker subprocess in production, so a crash
    there doesn't take the whole run down.

    Returns counts instead of calling `log_entry_fields` directly:
    `log_entry_fields` is contextvar-based and invisible across a process
    boundary, so the caller -- always running in the parent process,
    subprocess pool or not -- logs them itself from the returned result.
    """
    doc = fitz.open(file_path)
    try:
        return _extract_page_texts_with_counts(doc, pages)
    finally:
        doc.close()


def is_likely_image_only(doc: fitz.Document) -> bool:
    """True for a single-page PDF with no real text layer and negligible
    legible text at a low-DPI OCR pass -- e.g. a poster/battle-map, a
    dungeon-tile asset, or other single-page image with nothing worth
    extracting.

    Deliberately conservative: a genuine multi-page document, or any page
    with a real text layer, is never flagged, so this only ever trims
    single-page image-dominated content.
    """
    if doc.page_count != 1:
        return False
    page = doc[0]
    if _has_extractable_text(page):
        return False
    image = render_page_image(page, dpi=_IMAGE_ONLY_OCR_DPI)
    text = ocr_page_image(image)
    return len(text.split()) < _IMAGE_ONLY_WORD_THRESHOLD


def is_likely_image_only_isolated(file_path: Path) -> bool:
    """Same check as `is_likely_image_only`, but opens `file_path` itself
    and is meant to be run through `WorkerPool.submit` -- the render+OCR
    call is the same risky PyMuPDF/tesseract combination used elsewhere in
    this module, so it needs the same subprocess isolation and timeout.
    """
    doc = fitz.open(file_path)
    try:
        if doc.needs_pass:
            return False
        return is_likely_image_only(doc)
    finally:
        doc.close()


def sample_text_json(page_texts: dict[int, str]) -> str:
    """`{"pages": {"<1-indexed page number>": "<text>", ...}}` for storage.

    Keyed by actual page number (not list position) so gaps between
    first-N and last-N samples are self-evident.
    """
    pages = {str(page_number + 1): text for page_number, text in page_texts.items()}
    return json.dumps({"pages": pages})
