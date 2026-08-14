from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
from pymediainfo import MediaInfo

from ...model import PdfMetadata
from ...tools.isolated_worker import IsolatedWorkerPool, WorkerPool
from ...tools.text_extraction import is_likely_image_only_isolated
from ..MetadataExtractor import MetadataExtractor

# Only the first few pages are sampled for text/image analysis - enough to
# characterize the document without paying the cost of scanning every page.
_TEXT_SAMPLE_PAGE_LIMIT = 5
_MIN_EXTRACTABLE_TEXT_CHARS = 20
_SCANNED_IMAGE_COVERAGE_THRESHOLD = 0.85

# Info-dict/XMP fields fitz exposes on doc.metadata that map directly onto our
# candidate field names. "creator" is deliberately excluded -- for PDFs it's
# the authoring *application* (e.g. "Adobe InDesign"), not a person, so it
# must not be picked up as the artist/author.
_FITZ_METADATA_FIELDS = frozenset({"title", "author", "subject", "keywords"})


def get_page_count(doc: fitz.Document) -> int:
    """Return the document's page count."""
    return doc.page_count


def get_is_encrypted(doc: fitz.Document) -> bool:
    """Return whether the document carries any encryption, password-protected or not.

    fitz auto-authenticates on open when no user password is required, which
    resets `doc.is_encrypted` to False even for owner-password/permission-
    restricted PDFs. `doc.metadata['encryption']` still reflects that state.
    """
    if doc.is_encrypted:
        return True
    return doc.metadata is not None and doc.metadata.get("encryption") is not None


def get_needs_password(doc: fitz.Document) -> bool:
    """Return whether a password is required to read the document's content."""
    return bool(doc.needs_pass)


def _sample_pages(doc: fitz.Document) -> list[fitz.Page]:
    return [doc[i] for i in range(min(doc.page_count, _TEXT_SAMPLE_PAGE_LIMIT))]


def _page_has_text(page: fitz.Page) -> bool:
    text = str(page.get_text("text"))
    return len(text.strip()) >= _MIN_EXTRACTABLE_TEXT_CHARS


def _page_image_coverage(page: fitz.Page) -> float:
    """Fraction of the page area covered by embedded images."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for image in page.get_images(full=True):
        xref = image[0]
        for rect in page.get_image_rects(xref):
            visible = rect & page.rect
            covered += visible.width * visible.height
    return covered / page_area


def get_has_extractable_text(doc: fitz.Document) -> bool | None:
    """Return whether any sampled page contains a real text layer."""
    if doc.needs_pass or doc.page_count == 0:
        return None
    return any(_page_has_text(page) for page in _sample_pages(doc))


def get_likely_scanned(doc: fitz.Document) -> bool | None:
    """Return whether sampled pages look like scans:
    image-dominated with no text layer."""
    if doc.needs_pass or doc.page_count == 0:
        return None
    for page in _sample_pages(doc):
        if (
            _page_has_text(page)
            or _page_image_coverage(page) < _SCANNED_IMAGE_COVERAGE_THRESHOLD
        ):
            return False
    return True


class PdfExtractor(MetadataExtractor):
    def __init__(self, file_path: Path, pool: WorkerPool | None = None) -> None:
        self._path = file_path
        self._media_info: MediaInfo = MediaInfo.parse(filename=file_path)
        self._doc: fitz.Document = fitz.open(file_path)
        self._pool: WorkerPool = pool if pool is not None else IsolatedWorkerPool()

    def extract_value(self, field: str) -> str | None:
        key = field.lower()
        if key in _FITZ_METADATA_FIELDS and self._doc.metadata is not None:
            value = self._doc.metadata.get(key)
            if value:
                text = str(value).strip()
                if text:
                    return text
        for track in self._media_info.general_tracks:
            value = getattr(track, key, None)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return None

    def extract_custom_metadata(self) -> Any | None:
        page_count = get_page_count(self._doc)
        is_encrypted = get_is_encrypted(self._doc)
        needs_password = get_needs_password(self._doc)
        has_extractable_text = get_has_extractable_text(self._doc)
        likely_scanned = get_likely_scanned(self._doc)
        likely_image_only = self._get_likely_image_only(page_count)
        return PdfMetadata(
            page_count=page_count,
            is_encrypted=is_encrypted,
            needs_password=needs_password,
            has_extractable_text=has_extractable_text,
            likely_scanned=likely_scanned,
            likely_image_only=likely_image_only,
        )

    def _get_likely_image_only(self, page_count: int) -> bool | None:
        """None mirrors `get_has_extractable_text`/`get_likely_scanned` --
        undetermined for an unreadable/empty document. `page_count != 1` is
        answered without OCR; only a genuine single-page candidate pays for
        the isolated render+OCR call.
        """
        if self._doc.needs_pass or page_count == 0:
            return None
        if page_count != 1:
            return False
        return self._pool.submit(is_likely_image_only_isolated, self._path)
