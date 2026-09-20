from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import fitz
from pytesseract import TesseractNotFoundError

from ._barcode import scan_publication_identifiers
from ._ocr import ocr_page_image
from ._pdf_rendering import render_page_image
from ._text_extraction import (
    _IMAGE_ONLY_OCR_DPI,
    _IMAGE_ONLY_WORD_THRESHOLD,
    _all_pages_oversized_and_textless,
    _has_extractable_text,
)
from .errors import (
    DependencyUnavailableError,
    DocumentProcessingError,
    InvalidInputError,
)
from .identifiers import PublicationIdentifier


class TextMethod(StrEnum):
    EMBEDDED = "embedded"
    OCR = "ocr"


@dataclass(frozen=True, slots=True)
class PageText:
    page: int
    text: str
    method: TextMethod


@dataclass(frozen=True, slots=True)
class TextExtraction:
    pages: tuple[PageText, ...]

    @property
    def pages_sampled(self) -> int:
        return len(self.pages)

    @property
    def pages_direct_extraction(self) -> int:
        return sum(page.method is TextMethod.EMBEDDED for page in self.pages)

    @property
    def pages_ocr(self) -> int:
        return sum(page.method is TextMethod.OCR for page in self.pages)


class ImageAssessmentStatus(StrEnum):
    IMAGE_ONLY = "image_only"
    NOT_IMAGE_ONLY = "not_image_only"
    INDETERMINATE = "indeterminate"


class ImageAssessmentReason(StrEnum):
    OVERSIZED_TEXTLESS_PAGES = "oversized_textless_pages"
    NEGLIGIBLE_OCR_TEXT = "negligible_ocr_text"
    MEANINGFUL_OCR_TEXT = "meaningful_ocr_text"
    EMBEDDED_TEXT = "embedded_text"
    MULTIPAGE_DOCUMENT = "multipage_document"
    PASSWORD_PROTECTED = "password_protected"
    EMPTY_DOCUMENT = "empty_document"


@dataclass(frozen=True, slots=True)
class PdfImageAssessment:
    status: ImageAssessmentStatus
    reason: ImageAssessmentReason
    pages_assessed: tuple[int, ...]


def _selected_pages(
    path: Path, doc: fitz.Document, pages: tuple[int, ...] | None
) -> tuple[int, ...]:
    if pages is None:
        return tuple(range(doc.page_count))
    if not pages:
        raise InvalidInputError("pages cannot be empty")
    selected = tuple(dict.fromkeys(pages))
    for page in selected:
        if isinstance(page, bool) or not isinstance(page, int):
            raise InvalidInputError("page indexes must be integers")
        if page < 0 or page >= doc.page_count:
            raise InvalidInputError(
                f"page index {page} is outside {path} (page count {doc.page_count})"
            )
    return selected


def extract_text(path: Path, pages: tuple[int, ...] | None = None) -> TextExtraction:
    """Extract embedded text or OCR from every requested PDF page."""
    try:
        doc = fitz.open(path)
    except Exception as error:
        raise DocumentProcessingError(path, "open PDF") from error
    try:
        if doc.needs_pass:
            raise DocumentProcessingError(path, "read password-protected PDF")
        selected = _selected_pages(path, doc, pages)
        extracted: list[PageText] = []
        for page_number in selected:
            try:
                page = doc[page_number]
                if _has_extractable_text(page):
                    text = str(page.get_text("text"))
                    method = TextMethod.EMBEDDED
                else:
                    text = ocr_page_image(render_page_image(page))
                    method = TextMethod.OCR
                extracted.append(PageText(page_number, text.strip(), method))
            except TesseractNotFoundError as error:
                raise DependencyUnavailableError(
                    "Tesseract is required to OCR textless PDF pages"
                ) from error
            except Exception as error:
                raise DocumentProcessingError(
                    path, "extract PDF text", page_number
                ) from error
        return TextExtraction(tuple(extracted))
    finally:
        doc.close()


def scan_identifiers(
    path: Path, pages: tuple[int, ...] | None = None
) -> tuple[PublicationIdentifier, ...]:
    """Return every valid ISBN/ISSN barcode on the requested PDF pages."""
    try:
        doc = fitz.open(path)
    except Exception as error:
        raise DocumentProcessingError(path, "open PDF") from error
    try:
        if doc.needs_pass:
            raise DocumentProcessingError(path, "read password-protected PDF")
        selected = _selected_pages(path, doc, pages)
        try:
            return scan_publication_identifiers(doc, set(selected))
        except Exception as error:
            raise DocumentProcessingError(path, "scan PDF identifiers") from error
    finally:
        doc.close()


def assess_images(
    path: Path, pages: tuple[int, ...] | None = None
) -> PdfImageAssessment:
    """Assess whether the requested PDF pages are likely image-only content."""
    try:
        doc = fitz.open(path)
    except Exception as error:
        raise DocumentProcessingError(path, "open PDF") from error
    try:
        if doc.needs_pass:
            return PdfImageAssessment(
                ImageAssessmentStatus.INDETERMINATE,
                ImageAssessmentReason.PASSWORD_PROTECTED,
                (),
            )
        selected = _selected_pages(path, doc, pages)
        if not selected:
            return PdfImageAssessment(
                ImageAssessmentStatus.INDETERMINATE,
                ImageAssessmentReason.EMPTY_DOCUMENT,
                (),
            )
        try:
            if pages is None and _all_pages_oversized_and_textless(doc):
                return PdfImageAssessment(
                    ImageAssessmentStatus.IMAGE_ONLY,
                    ImageAssessmentReason.OVERSIZED_TEXTLESS_PAGES,
                    selected,
                )
            if pages is not None:
                selected_doc_pages = [doc[index] for index in selected]
                if all(
                    not _has_extractable_text(page)
                    and (page.rect.width > 20 * 72 or page.rect.height > 20 * 72)
                    for page in selected_doc_pages
                ):
                    return PdfImageAssessment(
                        ImageAssessmentStatus.IMAGE_ONLY,
                        ImageAssessmentReason.OVERSIZED_TEXTLESS_PAGES,
                        selected,
                    )
            if len(selected) != 1:
                return PdfImageAssessment(
                    ImageAssessmentStatus.NOT_IMAGE_ONLY,
                    ImageAssessmentReason.MULTIPAGE_DOCUMENT,
                    selected,
                )
            page = doc[selected[0]]
            if _has_extractable_text(page):
                return PdfImageAssessment(
                    ImageAssessmentStatus.NOT_IMAGE_ONLY,
                    ImageAssessmentReason.EMBEDDED_TEXT,
                    selected,
                )
            text = ocr_page_image(render_page_image(page, dpi=_IMAGE_ONLY_OCR_DPI))
            image_only = len(text.split()) < _IMAGE_ONLY_WORD_THRESHOLD
            return PdfImageAssessment(
                ImageAssessmentStatus.IMAGE_ONLY
                if image_only
                else ImageAssessmentStatus.NOT_IMAGE_ONLY,
                ImageAssessmentReason.NEGLIGIBLE_OCR_TEXT
                if image_only
                else ImageAssessmentReason.MEANINGFUL_OCR_TEXT,
                selected,
            )
        except TesseractNotFoundError as error:
            raise DependencyUnavailableError(
                "Tesseract is required to assess textless PDF pages"
            ) from error
        except Exception as error:
            raise DocumentProcessingError(path, "assess PDF images") from error
    finally:
        doc.close()
