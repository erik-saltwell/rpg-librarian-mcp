from __future__ import annotations

from sqlmodel import Field

from .core import EntryMetadataBase
from .LengthUnit import LengthUnit


class MeshMetadata(EntryMetadataBase, table=True):
    """Type-specific metadata for Entry rows where media_type == mesh.

    `unit` applies to both the bounding box dimensions and `surface_area` --
    a single unit-relative value set per row.
    """

    bounding_box_x: float | None = Field(default=None, nullable=True)
    bounding_box_y: float | None = Field(default=None, nullable=True)
    bounding_box_z: float | None = Field(default=None, nullable=True)
    surface_area: float | None = Field(default=None, nullable=True)
    unit: LengthUnit | None = Field(default=None, nullable=True)
