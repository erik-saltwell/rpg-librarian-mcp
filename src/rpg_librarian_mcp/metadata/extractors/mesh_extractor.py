from __future__ import annotations

import contextlib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

import trimesh
import trimesh.util
import trimesh.visual

from ...model import LengthUnit, MeshMetadata
from ...tools.isolated_worker import IsolatedWorkerPool, WorkerPool
from ..MetadataExtractor import MetadataExtractor


class BoundingBoxExtents(NamedTuple):
    x_mm: float
    y_mm: float
    z_mm: float


_3MF_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

# STL files have no embedded unit; millimetres is the 3D printing convention.
_STL_ASSUMED_UNIT = "mm"

# 3MF spec defaults to millimetres.
_3MF_UNIT_MAP = {
    "millimeter": "mm",
    "centimeter": "cm",
    "inch": "in",
    "foot": "ft",
    "meter": "m",
    "micron": "um",
}


def units_from_metadata(file_path: Path) -> str:
    try:
        with zipfile.ZipFile(file_path) as zf:
            model_files = [n for n in zf.namelist() if n.lower().endswith(".model")]
            for model_file in model_files:
                with zf.open(model_file) as f:
                    try:
                        tree = ET.parse(f)
                    except ET.ParseError:
                        return "mm"

                    root = tree.getroot()
                    raw_unit = root.get("unit")
                    if raw_unit:
                        unit = _3MF_UNIT_MAP.get(raw_unit.lower(), raw_unit)
                        return unit
        return "mm"

    except Exception:
        return "mm"


def _extract_3mf_metadata(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}

    try:
        with zipfile.ZipFile(path) as zf:
            model_files = [n for n in zf.namelist() if n.lower().endswith(".model")]
            for model_file in model_files:
                with zf.open(model_file) as f:
                    try:
                        tree = ET.parse(f)
                    except ET.ParseError:
                        continue

                    root = tree.getroot()

                    for md in root.findall(f"{{{_3MF_NS}}}metadata"):
                        name = (md.get("name") or "").lower().strip()
                        value = (md.text or "").strip()
                        if name and value:
                            meta[name] = value

    except Exception:
        pass

    return meta


def get_extents_from_mesh(mesh: trimesh.Trimesh) -> BoundingBoxExtents:
    """Axis-aligned extents, not the minimum-oriented bounding box.

    `mesh.bounding_box` computes a convex hull (via scipy/Qhull) to find the
    minimum-volume oriented box -- for a dense, complex mesh (e.g. a 3D print
    file with thousands of thin support struts) that hull computation can
    blow up in memory/time badly enough to crash the whole process. `bounds`
    is a plain min/max over vertices: no hull, no scipy, no equivalent
    failure mode -- at the cost of being larger than the true minimum box
    for a mesh that isn't axis-aligned.
    """
    bounds_min, bounds_max = mesh.bounds
    extents = bounds_max - bounds_min
    return BoundingBoxExtents(
        x_mm=round(float(extents[0]), 4),
        y_mm=round(float(extents[1]), 4),
        z_mm=round(float(extents[2]), 4),
    )


def get_surface_area_cm_from_mesh(mesh: trimesh.Trimesh) -> float | None:
    surface_area: float | None = None
    with contextlib.suppress(Exception):
        surface_area = round(float(mesh.area) / 100, 4)  # mm² → cm²
    return surface_area


def has_textures_from_mesh(mesh: trimesh.Trimesh) -> bool:
    return isinstance(mesh.visual, trimesh.visual.TextureVisuals)


def units_from_mesh(file_path: Path) -> str | None:
    return _STL_ASSUMED_UNIT


def _length_unit_from_raw(raw_unit: str | None) -> LengthUnit | None:
    if raw_unit is None:
        return None
    normalized = {"in": "inch"}.get(raw_unit, raw_unit)
    try:
        return LengthUnit(normalized)
    except ValueError:
        return None


class MeshExtractionResult(NamedTuple):
    bounding_box_x: float | None
    bounding_box_y: float | None
    bounding_box_z: float | None
    surface_area: float | None
    unit: str | None


def extract_mesh_metadata(file_path: Path) -> MeshExtractionResult:
    """Load `file_path` and compute its geometry summary.

    This is the actual risky call -- `trimesh.load` on an arbitrary,
    possibly-huge, user-supplied 3D file -- so it's run through
    `WorkerPool.submit` (a subprocess in production) instead of directly in
    `MeshExtractor.__init__`. Must stay a plain top-level function taking/
    returning only picklable primitives: nothing here can hand back the
    `trimesh.Trimesh` object itself.

    `process=False` skips trimesh's default vertex-merge/dedup pass. We
    only ever read `bounds` (plain min/max) and `area` (sum of face areas)
    off the result, neither of which needs merged topology -- but the
    merge itself is the expensive part for a dense, support-strut-heavy
    3D-print STL (millions of near-duplicate vertices), and has taken down
    a whole run's process before. See `get_extents_from_mesh` below for the
    same reasoning applied to the (now-avoided) convex-hull bounding box.
    """
    loaded = trimesh.load(str(file_path), force="mesh", process=False)
    mesh = loaded if isinstance(loaded, trimesh.Trimesh) else None

    extents: BoundingBoxExtents | None = None
    surface_area: float | None = None
    if mesh is not None:
        extents = get_extents_from_mesh(mesh)
        surface_area = get_surface_area_cm_from_mesh(mesh)

    return MeshExtractionResult(
        bounding_box_x=extents.x_mm if extents is not None else None,
        bounding_box_y=extents.y_mm if extents is not None else None,
        bounding_box_z=extents.z_mm if extents is not None else None,
        surface_area=surface_area,
        unit=units_from_mesh(file_path),
    )


class MeshExtractor(MetadataExtractor):
    def __init__(self, file_path: Path, pool: WorkerPool | None = None):
        self._path = file_path
        self._meta = _extract_3mf_metadata(file_path)
        self._pool: WorkerPool = pool if pool is not None else IsolatedWorkerPool()
        self._result: MeshExtractionResult = self._pool.submit(
            extract_mesh_metadata, file_path
        )

    def extract_value(self, field: str) -> str | None:
        key = field.lower()
        for meta_key, meta_value in self._meta.items():
            if meta_key.lower() == key:
                text = meta_value.strip()
                if text:
                    return text
        return None

    def extract_custom_metadata(self) -> Any | None:
        result = self._result
        return MeshMetadata(
            bounding_box_x=result.bounding_box_x,
            bounding_box_y=result.bounding_box_y,
            bounding_box_z=result.bounding_box_z,
            surface_area=result.surface_area,
            unit=_length_unit_from_raw(result.unit),
        )
