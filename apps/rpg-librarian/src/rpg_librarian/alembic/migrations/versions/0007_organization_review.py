"""Persistent organization review coverage, runs, and decisions.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_coverage",
        sa.Column("group_key", sa.String(), primary_key=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
    )

    def timestamps():
        return [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        ]

    op.create_table(
        "organization_run",
        *timestamps(),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("group_keys", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
    )
    for name in ("scope", "status"):
        op.create_index(f"ix_organization_run_{name}", "organization_run", [name])
    # No entry FK: grouping files into packs intentionally replaces entry IDs.
    op.create_table(
        "organization_finding",
        *timestamps(),
        sa.Column("group_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("file_ids", sa.JSON(), nullable=False),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.Column("resolved_at", sa.DateTime()),
        sa.Column("resolution_note", sa.String()),
    )
    for name in ("group_key", "status"):
        op.create_index(
            f"ix_organization_finding_{name}", "organization_finding", [name]
        )


def downgrade() -> None:
    for table in ("organization_finding", "organization_run"):
        for name in (
            ("group_key", "status")
            if table.endswith("finding")
            else ("scope", "status")
        ):
            op.drop_index(f"ix_{table}_{name}", table_name=table)
        op.drop_table(table)
    op.drop_table("organization_coverage")
