from __future__ import annotations

from sqlmodel import Field

from ..model.core import EntityBase
from ..utils.pydantic_aliases import NonEmptyStr


class Product(EntityBase, table=True):
    title: NonEmptyStr = Field(nullable=False, index=False)
    description: NonEmptyStr = Field(nullable=False, index=False)
    artists: NonEmptyStr = Field(nullable=False, index=False)
    publisher: NonEmptyStr = Field(nullable=False, index=False)
    year: NonEmptyStr = Field(nullable=False, index=False)
