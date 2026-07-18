from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from .base import ExtractionResult

# Disable Pillow's decompression-bomb limit: this library legitimately
# contains very large scanned images/maps that would otherwise raise
# DecompressionBombError.
Image.MAX_IMAGE_PIXELS = None

_ALPHA_MODES = {"RGBA", "LA", "PA"}


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in _ALPHA_MODES:
        return True
    return "transparency" in image.info


def _exif_base_metadata(image: Image.Image) -> dict[str, str]:
    try:
        exif = image.getexif()
    except Exception:
        return {}
    if not exif:
        return {}
    tags = {ExifTags.TAGS.get(tag_id, tag_id): value for tag_id, value in exif.items()}
    base_metadata: dict[str, str] = {}
    artist = tags.get("Artist")
    if artist:
        base_metadata["artist"] = str(artist)
    copyright_ = tags.get("Copyright")
    if copyright_:
        base_metadata["copyright"] = str(copyright_)
    return base_metadata


def extract(path: Path) -> ExtractionResult:
    media_type_metadata: dict[str, Any] = {}
    base_metadata: dict[str, str] = {}
    with Image.open(path) as image:
        width, height = image.size
        media_type_metadata["width"] = width
        media_type_metadata["height"] = height
        media_type_metadata["pixel_count"] = width * height
        media_type_metadata["has_alpha"] = _has_alpha(image)

        exif_metadata = _exif_base_metadata(image)
        artist = exif_metadata.get("artist")
        if artist:
            media_type_metadata["artists"] = artist
            base_metadata["artist"] = artist
        copyright_ = exif_metadata.get("copyright")
        if copyright_:
            media_type_metadata["copyright"] = copyright_
            base_metadata["copyright"] = copyright_

    return ExtractionResult(media_type_metadata=media_type_metadata, base_metadata=base_metadata)
