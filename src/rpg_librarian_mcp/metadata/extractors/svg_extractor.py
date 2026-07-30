from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ...model import ImageMetadata
from ..MetadataExtractor import MetadataExtractor

# Maps base-metadata candidate names onto the local element name that carries
# the value inside an SVG. Titles come from either <title> or Dublin Core
# <dc:title>; the remaining fields are Dublin Core elements in <metadata>.
_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "artist": "creator",
    "artists": "creator",
    "creator": "creator",
    "author": "creator",
    "authors": "creator",
    "publisher": "publisher",
    "organization": "publisher",
    "copyright": "rights",
    "rights": "rights",
    "date": "date",
}

_LENGTH_RE = re.compile(r"^\s*([+-]?[0-9]*\.?[0-9]+)\s*([a-z%]*)\s*$", re.IGNORECASE)


def _local_name(tag: str) -> str:
    """Strip any XML namespace, so '{http://www.w3.org/2000/svg}title' -> 'title'."""
    return tag.rsplit("}", 1)[-1]


def parse_length(raw: str | None) -> tuple[float | None, str | None]:
    """Split an SVG length like '64px' or '20mm' into (value, unit).

    Percentages and unparsable values yield (None, None): they carry no
    intrinsic size, so the caller should fall back to the viewBox.
    """
    if not raw:
        return None, None
    match = _LENGTH_RE.match(raw)
    if match is None:
        return None, None
    unit = match.group(2).lower() or None
    if unit == "%":
        return None, None
    return float(match.group(1)), unit


def parse_view_box(raw: str | None) -> tuple[float | None, float | None]:
    """Return the (width, height) carried by a 'min-x min-y width height' viewBox."""
    if not raw:
        return None, None
    parts = re.split(r"[\s,]+", raw.strip())
    if len(parts) != 4:
        return None, None
    try:
        return float(parts[2]), float(parts[3])
    except ValueError:
        return None, None


class SvgExtractor(MetadataExtractor):
    def __init__(self, file_path: Path) -> None:
        # SVG is XML, not raster data; parse the document tree once. Malformed
        # or unreadable files degrade to empty metadata rather than raising,
        # matching how the mesh/pdf extractors handle unparsable inputs.
        self._root: ET.Element | None
        try:
            self._root = ET.parse(file_path).getroot()
        except ET.ParseError, OSError:
            self._root = None

    def extract_value(self, field: str) -> str | None:
        if self._root is None:
            return None
        key = _FIELD_MAP.get(field.lower())
        if key is None:
            return None
        for element in self._root.iter():
            if _local_name(element.tag) == key and element.text:
                text = element.text.strip()
                if text:
                    return text
        return None

    def extract_custom_metadata(self) -> Any:
        if self._root is None:
            return ImageMetadata()

        width, _width_unit = parse_length(self._root.get("width"))
        height, _height_unit = parse_length(self._root.get("height"))

        # When width/height are absent or percentage-based, the viewBox gives the
        # intrinsic drawing size in user units.
        if width is None or height is None:
            vb_width, vb_height = parse_view_box(self._root.get("viewBox"))
            width = width if width is not None else vb_width
            height = height if height is not None else vb_height

        int_width = round(width) if width is not None else None
        int_height = round(height) if height is not None else None
        pixel_count = (
            int_width * int_height
            if int_width is not None and int_height is not None
            else None
        )
        return ImageMetadata(
            width=int_width,
            height=int_height,
            has_alpha=True,
            pixel_count=pixel_count,
        )
