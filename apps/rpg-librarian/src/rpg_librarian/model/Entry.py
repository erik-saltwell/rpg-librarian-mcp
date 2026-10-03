from __future__ import annotations

from sqlalchemy import Column, ForeignKey, UniqueConstraint
from sqlmodel import Field

from .core import EntityBase, EntryType, EntryTypeType


class Entry(EntityBase, table=True):
    """The identity that tools, evidence, errors, and review flags use for an item.

    A discriminated union: `type` says which foreign key holds the item. Today every
    entry is a `file` entry with `file_id` set; other kinds (packs) add their own
    nullable foreign key and `type` value. `product_id` is the item's product link,
    which used to live on `file`. `disposition` stays on `file`.
    """

    __tablename__ = "entry"
    __table_args__ = (UniqueConstraint("file_id", name="uq_entry_file_id"),)

    type: EntryType = Field(sa_column=Column(EntryTypeType(length=16), nullable=False))
    file_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("file.id", ondelete="CASCADE"), nullable=True),
    )
    product_id: int | None = Field(default=None, foreign_key="product.id", index=True)
