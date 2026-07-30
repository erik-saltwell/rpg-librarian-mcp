from typing import cast

import pytest
from PIL import Image

from rpg_librarian_mcp.tools import ocr


def test_check_tesseract_available_raises_when_binary_missing(monkeypatch):
    def _raise():
        raise ocr.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr.pytesseract, "get_tesseract_version", _raise)

    with pytest.raises(ocr.pytesseract.TesseractNotFoundError):
        ocr.check_tesseract_available()


def test_check_tesseract_available_is_a_noop_when_binary_present(monkeypatch):
    monkeypatch.setattr(ocr.pytesseract, "get_tesseract_version", lambda: "5.0.0")

    ocr.check_tesseract_available()  # must not raise


def test_ocr_page_image_delegates_to_pytesseract(monkeypatch):
    monkeypatch.setattr(
        ocr.pytesseract, "image_to_string", lambda image: f"text from {image}"
    )

    fake_image = cast(Image.Image, "fake-image")

    assert ocr.ocr_page_image(fake_image) == "text from fake-image"
