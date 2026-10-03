from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, UniqueConstraint
from sqlmodel import Field

from .core import EntityBase, EntryType, EntryTypeType


class Entry(EntityBase, table=True):
    """The identity that tools, evidence, errors, and review flags use for an item.

    A discriminated union: `type` says which foreign key holds the item. A `file` entry
    has `file_id` set; a `pack` entry has `pack_id` set (a pack's member files have no
    entry of their own). `product_id` is the item's product link. A file entry's
    disposition is on its `file`; a pack entry's is on its `pack`.
    """

    __tablename__ = "entry"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_entry_file_id"),
        UniqueConstraint("pack_id", name="uq_entry_pack_id"),
        CheckConstraint(
            "(type = 'file' AND file_id IS NOT NULL AND pack_id IS NULL) OR "
            "(type = 'pack' AND pack_id IS NOT NULL AND file_id IS NULL)",
            name="ck_entry_one_item",
        ),
    )

    type: EntryType = Field(sa_column=Column(EntryTypeType(length=16), nullable=False))
    file_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("file.id", ondelete="CASCADE"), nullable=True),
    )
    pack_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("pack.id", ondelete="CASCADE"), nullable=True),
    )
    product_id: int | None = Field(default=None, foreign_key="product.id", index=True)
