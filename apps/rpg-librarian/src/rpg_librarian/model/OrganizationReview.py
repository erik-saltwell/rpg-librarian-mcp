"""Durable review state; historical IDs are evidence, not cascading foreign keys."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel

from .core import EntityBase, UTCDateTime, utc_now


class OrganizationCoverage(SQLModel, table=True):
    __tablename__ = "organization_coverage"

    group_key: str = Field(primary_key=True)
    fingerprint: str
    summary: str
    reviewed_at: datetime = Field(default_factory=utc_now, sa_type=UTCDateTime)


class OrganizationRun(EntityBase, table=True):
    __tablename__ = "organization_run"

    scope: str = Field(index=True)
    status: str = Field(default="active", index=True)
    group_keys: list[str] = Field(default_factory=list, sa_type=JSON)
    results: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)


class OrganizationFinding(EntityBase, table=True):
    __tablename__ = "organization_finding"

    group_key: str = Field(index=True)
    status: str = Field(index=True)
    file_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    record: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    resolved_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    resolution_note: str | None = None
