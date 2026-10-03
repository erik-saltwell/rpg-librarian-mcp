from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import JSON, Field, SQLModel

from .core import UTCDateTime, utc_now


class FolderSearch(SQLModel, table=True):
    """A cached Google search `find-packs` made for a folder name, keyed by its query.

    The query is the normalized folder and parent words, so two folders with the same
    name share one paid request. A pack formed from a searched folder copies the row
    into its own `google_search_result`, so `enrich` does not search again.
    """

    __tablename__ = "folder_search"

    query: str = Field(primary_key=True)
    results: list[dict[str, Any]] = Field(
        default_factory=list, sa_type=JSON, nullable=False
    )
    fetched_at: datetime = Field(default_factory=utc_now, sa_type=UTCDateTime)
