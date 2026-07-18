from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

import trimesh

from .base import ExtractionResult

_DEFAULT_UNIT = "mm"

# 3MF-declared unit -> our short unit code, and short code -> mm-per-unit
# conversion factor, so bounding box/area always land in the schema's fixed
# units (mm, cm2) regardless of what the source file declared.
_3MF_UNIT_ALIASES = {
    "micron": "micron",
    "millimeter": "mm",
    "centimeter": "cm",
    "inch": "in",
    "foot": "ft",
    "meter": "m",
}
_MM_PER_UNIT = {
    "micron": 0.001,
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "ft": 304.8,
    "m": 1000.0,
}

_3MF_MODEL_XML_PATH = "3D/3dmodel.model"
_3MF_MODEL_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
# Dublin-Core-ish <metadata name="...">value</metadata> elements 3MF allows at
# the model root, mapped to our universal base-metadata fields.
_3MF_METADATA_FIELDS = {
    "Title": "title",
    "Designer": "artist",
    "Publisher": "publisher",
    "Rights": "copyright",
    "Description": "description",
}


def _read_3mf_unit_and_metadata(path: Path) -> tuple[str, dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive, archive.open(_3MF_MODEL_XML_PATH) as handle:
            root = ElementTree.parse(handle).getroot()
    except Exception:
        return _DEFAULT_UNIT, {}

    unit = _3MF_UNIT_ALIASES.get(root.get("unit", ""), _DEFAULT_UNIT)

    base_metadata: dict[str, str] = {}
    for element in root.iter(f"{_3MF_MODEL_NS}metadata"):
        name = element.get("name")
        base_field = _3MF_METADATA_FIELDS.get(name or "")
        if base_field and element.text:
            base_metadata[base_field] = element.text.strip()

    return unit, base_metadata


def extract(path: Path) -> ExtractionResult:
    if path.suffix.lower() == ".3mf":
        unit, base_metadata = _read_3mf_unit_and_metadata(path)
    else:
        unit, base_metadata = _DEFAULT_UNIT, {}

    try:
        geometry = trimesh.load(path)
    except Exception:
        return ExtractionResult(media_type_metadata={"unit": unit}, base_metadata=base_metadata)

    media_type_metadata: dict[str, float | str] = {"unit": unit}
    try:
        mm_per_unit = _MM_PER_UNIT[unit]
        extents = geometry.bounding_box.extents
        media_type_metadata["bounding_box_x_mm"] = float(extents[0]) * mm_per_unit
        media_type_metadata["bounding_box_y_mm"] = float(extents[1]) * mm_per_unit
        media_type_metadata["bounding_box_z_mm"] = float(extents[2]) * mm_per_unit
        media_type_metadata["surface_area_cm2"] = float(geometry.area) * (mm_per_unit**2) / 100
    except Exception:
        pass

    return ExtractionResult(media_type_metadata=media_type_metadata, base_metadata=base_metadata)
