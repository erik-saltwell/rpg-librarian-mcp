"""rename sha356 to sha256

Revision ID: f27fa1d64492
Revises: a0982134c448
Create Date: 2026-07-25 17:45:43.854167

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f27fa1d64492"
down_revision: str | Sequence[str] | None = "a0982134c448"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("entry", schema=None) as batch_op:
        batch_op.alter_column(
            "sha356",
            new_column_name="sha256",
            existing_type=sa.String(),
            existing_nullable=False,
        )
    op.drop_index("ix_entry_sha356", table_name="entry")
    op.create_index("ix_entry_sha256", "entry", ["sha256"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("entry", schema=None) as batch_op:
        batch_op.alter_column(
            "sha256",
            new_column_name="sha356",
            existing_type=sa.String(),
            existing_nullable=False,
        )
    op.drop_index("ix_entry_sha256", table_name="entry")
    op.create_index("ix_entry_sha356", "entry", ["sha356"], unique=False)
