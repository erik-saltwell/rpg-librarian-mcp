from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from ...model import ImageMetadata
from ..MetadataExtractor import MetadataExtractor

# This catalog indexes a trusted local library, so Pillow's decompression-bomb
# guard (which raises for images above ~179M pixels as a possible DOS attack) only
# rejects legitimately huge maps and posters. Disable the limit so they extract.
Image.MAX_IMAGE_PIXELS = None


def get_image_width(image: Image.Image) -> int:
    return image.width


def get_image_height(image: Image.Image) -> int:
    return image.height


def get_has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "RGBa", "LA", "La", "PA"):
        return True
    if image.mode == "P":
        return "transparency" in image.info
    return False


def get_exif_str(image: Image.Image, tag_name: str) -> str | None:
    exif = image.getexif()
    if not exif:
        return None
    tag_id = next((k for k, v in ExifTags.TAGS.items() if v == tag_name), None)
    if tag_id is None:
        return None
    val = exif.get(tag_id)
    if val is None:
        return None
    text = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else str(val)
    return text.strip() or None


class ImageExtractor(MetadataExtractor):
    def __init__(self, file_path: Path) -> None:
        self._image = Image.open(file_path)
        self._image.load()

    def extract_value(self, field: str) -> str | None:
        key = field.lower()
        exif = self._image.getexif()
        if not exif:
            return None
        for tag_id, tag_name in ExifTags.TAGS.items():
            if tag_name.lower() == key:
                val = exif.get(tag_id)
                if val is not None:
                    text = (
                        val.decode("utf-8", errors="replace")
                        if isinstance(val, bytes)
                        else str(val)
                    )
                    text = text.strip()
                    if text:
                        return text
        return None

    def extract_custom_metadata(self) -> Any | None:
        image = self._image
        width = get_image_width(image)
        height = get_image_height(image)
        return ImageMetadata(
            width=width,
            height=height,
            has_alpha=get_has_alpha(image),
            pixel_count=width * height,
        )
