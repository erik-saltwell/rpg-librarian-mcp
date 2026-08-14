from __future__ import annotations

import fitz
from PIL import Image

_RENDER_DPI = 300
_BASE_DPI = 72


def render_page_image(page: fitz.Page, dpi: int = _RENDER_DPI) -> Image.Image:
    """Render `page` to a PIL image at `dpi` (default `_RENDER_DPI`), for
    barcode scanning and OCR."""
    scale = dpi / _BASE_DPI
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
