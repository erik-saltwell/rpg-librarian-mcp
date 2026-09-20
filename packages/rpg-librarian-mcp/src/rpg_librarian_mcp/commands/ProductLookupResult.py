from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Source = Literal["rpggeek", "dtrpg", "isbn"]


class ProductCandidate(BaseModel):
    source: Source
    source_id: str
    title: str
    year_published: int | None = None


class ProductLookupDetails(BaseModel):
    source: Source
    source_id: str
    title: str
    year_published: int | None = None
    description: str | None = None
    publisher: str | None = None
    system: str | None = None
    creators: list[str] = []
    thumbnail_url: str | None = None
    rating: float | None = None
    categories: list[str] = []
