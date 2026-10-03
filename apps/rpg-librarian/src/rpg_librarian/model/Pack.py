from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field

from .core import (
    Disposition,
    DispositionType,
    EntityBase,
    PackFormation,
    PackFormationType,
)


class Pack(EntityBase, table=True):
    """A set of files with a collective identity and none of their own (a map pack, a
    token set, an audio set).

    Its catalog identity is its `Entry` (`type = 'pack'`), which carries the product
    link; its member files point here through `file.pack_id` and have no entry. The pack
    owns the disposition: a member's own `file.disposition` is ignored while it is a
    member (it is kept `unfiled`). `root_id` and `original_root_path` record where the
    pack was formed and never change; the current root is derived from the members,
    because `reorganize` moves them. `reason` and `evidence` record why it was formed.
    """

    __tablename__ = "pack"

    root_id: int = Field(foreign_key="root.id", index=True)
    original_root_path: str = Field(nullable=False)
    disposition: Disposition = Field(
        default=Disposition.unfiled,
        sa_column=Column(
            DispositionType(length=16),
            nullable=False,
            server_default=Disposition.unfiled.value,
        ),
    )
    formation: PackFormation = Field(
        sa_column=Column(PackFormationType(length=16), nullable=False)
    )
    reason: str | None = Field(default=None, nullable=True)
    evidence: dict[str, Any] | None = Field(default=None, sa_type=JSON, nullable=True)
