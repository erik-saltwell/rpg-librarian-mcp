from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, UniqueConstraint
from sqlmodel import Field

from rpg_librarian_tools.files import MediaType

from .core import (
    Disposition,
    DispositionType,
    EntityBase,
    MediaTypeType,
    UTCDateTime,
    utc_now,
)


class File(EntityBase, table=True):
    """One physical file occurrence on the share.

    Identified by `(root_id, relative_path)`; `sha256` is indexed but not unique,
    because each copy needs its own disposition and location. `created_at` is when
    the file was first seen. `sha256`, `mime_type`, and `media_type` are nullable so
    a row can exist (and carry `error` rows) before extraction has succeeded. Its
    product link lives on its `Entry`.
    """

    __tablename__ = "file"
    # `keep` requires a product, but the product is on `entry`, so that rule is
    # enforced by `update_product` rather than a CHECK constraint.
    __table_args__ = (UniqueConstraint("root_id", "relative_path"),)

    root_id: int = Field(foreign_key="root.id", index=True)
    relative_path: str = Field(nullable=False)

    size_bytes: int = Field(nullable=False)
    mtime: int = Field(nullable=False)  # whole seconds; SMB granularity varies
    mime_type: str | None = Field(default=None, nullable=True)
    media_type: MediaType | None = Field(
        default=None,
        sa_column=Column(MediaTypeType(length=32), nullable=True, index=True),
    )
    sha256: str | None = Field(default=None, nullable=True, index=True)

    disposition: Disposition = Field(
        default=Disposition.unfiled,
        sa_column=Column(
            DispositionType(length=16),
            nullable=False,
            index=True,
            server_default=Disposition.unfiled.value,
        ),
    )
    # A kept file's path below its product folder, filename included. Stored by
    # `reorganize` when the product first moves (NULL until then: worked out from
    # where the file sits) and cleared when the file is filed differently.
    subpath: str | None = Field(default=None, nullable=True)
    duplicate_of_id: int | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("file.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )

    missing_since: datetime | None = Field(default=None, sa_type=UTCDateTime)
    last_seen_at: datetime = Field(default_factory=utc_now, sa_type=UTCDateTime)
