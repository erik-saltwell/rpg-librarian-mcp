from __future__ import annotations

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from .core import EntityBase


class ProductLine(EntityBase, table=True):
    """A game, model line, or publisher within exactly one product type."""

    __tablename__ = "product_line"
    __table_args__ = (UniqueConstraint("product_type_id", "name"),)

    product_type_id: int = Field(foreign_key="product_type.id", index=True)
    name: str = Field(nullable=False)
