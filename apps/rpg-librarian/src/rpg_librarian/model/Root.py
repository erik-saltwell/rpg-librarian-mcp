from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field

from .core import EntityBase, RootKind, RootKindType, UTCDateTime


class Root(EntityBase, table=True):
    """A registered location: the library, or a staging dump.

    Paths in `File` are relative to a root, so a changed share mount point is a
    one-row update here. `init` enforces exactly one `library` root.
    """

    __tablename__ = "root"

    kind: RootKind = Field(
        sa_column=Column(RootKindType(length=16), nullable=False, index=True)
    )
    path: str = Field(nullable=False, unique=True)
    label: str | None = Field(default=None, nullable=True)
    last_scanned_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
