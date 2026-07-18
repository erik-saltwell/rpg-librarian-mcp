from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # pymupdf
from pymediainfo import MediaInfo

from .base import ExtractionResult

_SAMPLE_PAGE_COUNT = 5
_MIN_EXTRACTABLE_TEXT_CHARS = 20
_SCANNED_IMAGE_COVERAGE_THRESHOLD = 0.85

# MediaInfo general-track attribute -> universal base-metadata field.
_BASE_METADATA_ATTRS = {
    "title": "title",
    "performer": "artist",
    "publisher": "publisher",
    "copyright": "copyright",
    "genre": "genre",
}


def _sample_pages(doc: fitz.Document) -> list[fitz.Page]:
    return [doc[i] for i in range(min(_SAMPLE_PAGE_COUNT, doc.page_count))]


def _has_extractable_text(doc: fitz.Document) -> bool:
    return any(len(page.get_text().strip()) >= _MIN_EXTRACTABLE_TEXT_CHARS for page in _sample_pages(doc))


def _likely_scanned(doc: fitz.Document) -> bool:
    sampled = _sample_pages(doc)
    if not sampled:
        return False
    for page in sampled:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return False
        image_area = sum(
            max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
            for info in page.get_image_info()
            if (bbox := info.get("bbox")) is not None
        )
        if image_area / page_area < _SCANNED_IMAGE_COVERAGE_THRESHOLD:
            return False
    return True


def _base_metadata_from_media_info(path: Path) -> dict[str, str]:
    try:
        media_info = MediaInfo.parse(path)
    except Exception:
        return {}
    base_metadata: dict[str, str] = {}
    for track in media_info.general_tracks:
        for mediainfo_attr, base_field in _BASE_METADATA_ATTRS.items():
            value = getattr(track, mediainfo_attr, None)
            if value and base_field not in base_metadata:
                base_metadata[base_field] = value
    return base_metadata


def extract(path: Path) -> ExtractionResult:
    # fitz.open() failing outright (corrupt/non-PDF content) is a whole-file
    # failure and deliberately allowed to propagate -- the caller (sync.py)
    # records it as an extraction error rather than silently producing an
    # empty result. Only the two best-effort heuristics below, which can fail
    # even on an otherwise-valid PDF, are caught locally.
    media_type_metadata: dict[str, Any] = {}
    with fitz.open(path) as doc:
        media_type_metadata["page_count"] = doc.page_count
        media_type_metadata["is_encrypted"] = doc.is_encrypted
        media_type_metadata["needs_password"] = bool(doc.needs_pass)
        try:
            media_type_metadata["has_extractable_text"] = _has_extractable_text(doc)
        except Exception:
            pass
        try:
            media_type_metadata["likely_scanned"] = _likely_scanned(doc)
        except Exception:
            pass

    return ExtractionResult(
        media_type_metadata=media_type_metadata,
        base_metadata=_base_metadata_from_media_info(path),
    )
