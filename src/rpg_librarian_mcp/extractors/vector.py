from __future__ import annotations

import gzip
import re
from pathlib import Path
from xml.etree import ElementTree

from .base import ExtractionResult

_SVG_NS = "{http://www.w3.org/2000/svg}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"

# Dublin-Core element name -> universal base-metadata field.
_DC_METADATA_FIELDS = {
    "title": "title",
    "creator": "artist",
    "publisher": "publisher",
    "rights": "copyright",
    "description": "description",
}

_NUMERIC_PREFIX = re.compile(r"[-+]?\d*\.?\d+")


def _parse_length(value: str | None) -> float | None:
    if not value:
        return None
    match = _NUMERIC_PREFIX.match(value.strip())
    return float(match.group()) if match else None


def _read_root(path: Path) -> ElementTree.Element:
    if path.suffix.lower() == ".svgz":
        with gzip.open(path, "rb") as handle:
            return ElementTree.fromstring(handle.read())
    return ElementTree.parse(path).getroot()


def _dc_base_metadata(root: ElementTree.Element) -> dict[str, str]:
    base_metadata: dict[str, str] = {}
    for element in root.iter():
        if not element.tag.startswith(_DC_NS):
            continue
        local_name = element.tag[len(_DC_NS) :]
        base_field = _DC_METADATA_FIELDS.get(local_name)
        if base_field and element.text and base_field not in base_metadata:
            base_metadata[base_field] = element.text.strip()
    return base_metadata


def extract(path: Path) -> ExtractionResult:
    # A genuinely malformed SVG raising ElementTree.ParseError is a
    # whole-file failure, deliberately allowed to propagate so the caller
    # (sync.py) records it as an extraction error rather than silently
    # producing an empty result.
    root = _read_root(path)

    media_type_metadata: dict[str, float | str | None] = {
        "width": _parse_length(root.get("width")),
        "height": _parse_length(root.get("height")),
        "view_box": root.get("viewBox"),
    }
    width_attr = root.get("width") or ""
    units_match = re.search(r"[a-zA-Z%]+$", width_attr.strip())
    media_type_metadata["units"] = units_match.group() if units_match else None

    return ExtractionResult(
        media_type_metadata=media_type_metadata,
        base_metadata=_dc_base_metadata(root),
    )
