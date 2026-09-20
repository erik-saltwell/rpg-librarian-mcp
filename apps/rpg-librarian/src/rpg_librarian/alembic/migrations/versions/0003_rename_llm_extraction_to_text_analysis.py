"""rename file_llm_extraction to file_text_analysis

The table is named for where its data comes from (the stored text sample), not for
how it was produced. Error rows recorded under the old `llm` stage are relabelled.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("file_llm_extraction", "file_text_analysis")
    op.execute("UPDATE error SET stage = 'text_analysis' WHERE stage = 'llm'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE error SET stage = 'llm' WHERE stage = 'text_analysis'")
    op.rename_table("file_text_analysis", "file_llm_extraction")
