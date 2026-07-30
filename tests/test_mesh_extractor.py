from pathlib import Path

import pytest
import trimesh

from rpg_librarian_mcp.metadata.extractors import mesh_extractor
from rpg_librarian_mcp.metadata.extractors.mesh_extractor import MeshExtractor
from rpg_librarian_mcp.model import LengthUnit, MeshMetadata


def test_extract_custom_metadata_returns_mesh_dimensions_area_and_unit(monkeypatch):
    mesh = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    monkeypatch.setattr(mesh_extractor.trimesh, "load", lambda *args, **kwargs: mesh)

    metadata = MeshExtractor(Path("mini.stl")).extract_custom_metadata()

    assert isinstance(metadata, MeshMetadata)
    assert metadata.bounding_box_x == 10.0
    assert metadata.bounding_box_y == 20.0
    assert metadata.bounding_box_z == 30.0
    assert metadata.surface_area == 22.0
    assert metadata.unit == LengthUnit.mm


def test_unparseable_mesh_raises_instead_of_silently_returning_empty_metadata(
    monkeypatch,
):
    """Same bug shape as errors.md #3, for the mesh extractor: a file
    trimesh can't load must surface as a failure, not a successfully
    processed all-NULL metadata row."""

    def _raise(*args, **kwargs):
        raise ValueError("not a valid mesh file")

    monkeypatch.setattr(mesh_extractor.trimesh, "load", _raise)

    with pytest.raises(ValueError, match="not a valid mesh file"):
        MeshExtractor(Path("garbage.stl"))
