from __future__ import annotations

from sqlalchemy import Column, ForeignKey, UniqueConstraint
from sqlmodel import Field

from .core import EntityBase


class ProductLineAlias(EntityBase, table=True):
    """An alternate name for a line ("D&D 5e" for "Dungeons & Dragons").

    Uniqueness across the whole type (an alias may not equal another line's name
    or alias) is checked in code at write time; this table enforces it only per line.
    """

    __tablename__ = "product_line_alias"
    __table_args__ = (UniqueConstraint("product_line_id", "alias"),)

    product_line_id: int = Field(
        sa_column=Column(
            ForeignKey("product_line.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    alias: str = Field(nullable=False)
