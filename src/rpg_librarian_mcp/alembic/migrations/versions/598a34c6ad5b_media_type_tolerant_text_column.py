"""media_type tolerant text column

Revision ID: 598a34c6ad5b
Revises: 454ae90a7155
Create Date: 2026-07-28 15:39:56.917485

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import rpg_librarian_mcp.model.MediaType

# revision identifiers, used by Alembic.
revision: str = "598a34c6ad5b"
down_revision: str | Sequence[str] | None = "454ae90a7155"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("entry", schema=None) as batch_op:
        batch_op.alter_column(
            "media_type",
            existing_type=sa.VARCHAR(length=7),
            type_=rpg_librarian_mcp.model.MediaType.TolerantMediaType(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("entry", schema=None) as batch_op:
        batch_op.alter_column(
            "media_type",
            existing_type=rpg_librarian_mcp.model.MediaType.TolerantMediaType(
                length=32
            ),
            type_=sa.VARCHAR(length=7),
            existing_nullable=False,
        )
