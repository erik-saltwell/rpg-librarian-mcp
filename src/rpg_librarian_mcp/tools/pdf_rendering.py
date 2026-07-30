from __future__ import annotations

import fitz
from PIL import Image

_RENDER_DPI = 300
_BASE_DPI = 72


def render_page_image(page: fitz.Page) -> Image.Image:
    """Render `page` to a PIL image at `_RENDER_DPI`, for barcode scanning and OCR."""
    scale = _RENDER_DPI / _BASE_DPI
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
