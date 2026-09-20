from __future__ import annotations

from typing import ClassVar

from sqlmodel import Field

from ..model.core import EntityBase
from ..utils.pydantic_aliases import NonEmptyStr
from .ContentRole import ContentRole
from .IdentificationMethod import IdentificationMethod


class Product(EntityBase, table=True):
    UNKNOWN_SYSTEM: ClassVar[str] = "unknown"
    AGNOSTIC: ClassVar[str] = "Agnostic"

    title: NonEmptyStr | None = Field(default=None, nullable=True, index=False)
    description: NonEmptyStr | None = Field(default=None, nullable=True, index=False)
    artists: NonEmptyStr | None = Field(default=None, nullable=True, index=False)
    publisher: NonEmptyStr | None = Field(default=None, nullable=True, index=False)
    year: NonEmptyStr | None = Field(default=None, nullable=True, index=False)

    system: NonEmptyStr = Field(default=UNKNOWN_SYSTEM, nullable=False, index=True)
    identification_method: IdentificationMethod = Field(nullable=False, index=True)
    content_role: ContentRole | None = Field(default=None, nullable=True, index=True)
