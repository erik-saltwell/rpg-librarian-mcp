from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath
from typing import Self

from pydantic import NonNegativeInt, model_validator
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, ForeignKey

from ..utils.pydantic_aliases import NonEmptyStr
from .core import (
    EntityBase,
    ParentPathType,
    Sha256,
    validate_filename,
    validate_parent_path,
)
from .MediaType import MediaType, TolerantMediaType


class Entry(EntityBase, table=True):
    __table_args__ = (UniqueConstraint("parent_path", "filename"),)

    parent_path: Path = Field(
        sa_column=Column(
            ParentPathType(length=1024),
            nullable=False,
            index=True,
        )
    )
    filename: NonEmptyStr = Field(nullable=False, index=False)

    sha256: Sha256 = Field(
        nullable=False,
        index=True,
    )
    product_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("product.id"), nullable=True),
    )
    size_in_bytes: NonNegativeInt = Field(nullable=False, index=False)
    mime_type: NonEmptyStr = Field(nullable=False, index=False)
    media_type: MediaType = Field(
        sa_column=Column(TolerantMediaType(length=32), nullable=False, index=True)
    )

    @property
    def path(self) -> Path:
        return self.parent_path / self.filename

    @property
    def extension(self) -> str:
        return PurePosixPath(self.filename).suffix.lower()

    @property
    def parent_folder(self) -> str:
        return self.parent_path.name

    @property
    def grandparent_folder(self) -> str:
        return self.parent_path.parent.name

    @property
    def first_ancestor(self) -> str:
        return self.parent_path.parts[0]

    @property
    def second_ancestor(self) -> str:
        return self.parent_path.parts[1]

    @property
    def has_product(self) -> bool:
        return self.product_id is not None

    @model_validator(mode="after")
    def validate_path_fields(self) -> Self:
        validate_parent_path(self.parent_path)
        validate_filename(self.filename)
        return self
