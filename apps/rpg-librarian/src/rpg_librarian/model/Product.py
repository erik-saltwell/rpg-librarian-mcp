from __future__ import annotations

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from .core import EntityBase


class Product(EntityBase, table=True):
    """A set of files that shipped together, unique by name within its line."""

    __tablename__ = "product"
    __table_args__ = (UniqueConstraint("product_line_id", "name"),)

    product_line_id: int = Field(foreign_key="product_line.id", index=True)
    name: str = Field(nullable=False)

    publisher: str | None = Field(default=None, nullable=True)
    year: str | None = Field(default=None, nullable=True)
    artists: str | None = Field(default=None, nullable=True)
    description: str | None = Field(default=None, nullable=True)
