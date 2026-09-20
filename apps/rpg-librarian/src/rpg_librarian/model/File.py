from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, UniqueConstraint
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
    a row can exist (and carry `error` rows) before extraction has succeeded.
    """

    __tablename__ = "file"
    __table_args__ = (
        UniqueConstraint("root_id", "relative_path"),
        CheckConstraint(
            "disposition != 'keep' OR product_id IS NOT NULL",
            name="ck_file_keep_requires_product",
        ),
    )

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
    product_id: int | None = Field(default=None, foreign_key="product.id", index=True)
    duplicate_of_id: int | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("file.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )

    missing_since: datetime | None = Field(default=None, sa_type=UTCDateTime)
    last_seen_at: datetime = Field(default_factory=utc_now, sa_type=UTCDateTime)
