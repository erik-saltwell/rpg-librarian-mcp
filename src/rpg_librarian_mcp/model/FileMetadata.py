from __future__ import annotations

from sqlmodel import Field

from ..utils.pydantic_aliases import NonEmptyStr
from .core import EntryMetadataBase


class FileMetadata(EntryMetadataBase, table=True):
    """Generic metadata read from a file's own embedded properties.

    One row per Entry -- this is the `file_metadata` source specifically,
    not a shared table for every source. Other sources (RPGGeek/ISBN/
    DriveThruRPG lookups) get their own dedicated tables.
    """

    title: NonEmptyStr | None = Field(default=None, nullable=True)
    artist: NonEmptyStr | None = Field(default=None, nullable=True)
    publisher: NonEmptyStr | None = Field(default=None, nullable=True)
    copyright: NonEmptyStr | None = Field(default=None, nullable=True)
