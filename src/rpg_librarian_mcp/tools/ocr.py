from __future__ import annotations

import pytesseract
from PIL import Image


def check_tesseract_available() -> None:
    """Raise if the Tesseract system binary isn't installed/on PATH.

    Meant to be called once, up front, before scanning any entries -- a
    missing binary is an environment misconfiguration, not a per-file
    problem, so it should fail the whole command immediately rather than
    erroring every scanned PDF individually.
    """
    pytesseract.get_tesseract_version()


def ocr_page_image(image: Image.Image) -> str:
    """OCR'd text of a rendered page image."""
    return pytesseract.image_to_string(image)
