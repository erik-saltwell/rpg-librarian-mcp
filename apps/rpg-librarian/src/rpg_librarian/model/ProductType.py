from __future__ import annotations

from sqlmodel import Field

from .core import EntityBase


class ProductType(EntityBase, table=True):
    """A function-based top-level folder (`games`, `maps`, `vtt packs`, ...)."""

    __tablename__ = "product_type"

    name: str = Field(nullable=False, unique=True)
