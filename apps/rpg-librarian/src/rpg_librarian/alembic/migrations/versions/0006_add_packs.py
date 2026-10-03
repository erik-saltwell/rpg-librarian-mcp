"""add packs

A `pack` is a set of files with a collective identity and none of their own. It is a
second entry type: its `entry` row (`type = 'pack'`, `pack_id` set) carries the product
link, the pack row carries the disposition, and its member files point at it through
`file.pack_id` and have no entry. No catalog content changes: no packs exist yet.

- `pack`: root, original root folder, disposition, how it was formed, why, and the
  evidence it was formed on.
- `entry` is rebuilt with `pack_id` (unique, cascading) and a CHECK that exactly the
  foreign key of its `type` is set.
- `file.pack_id` (indexed, RESTRICT: a pack is only deleted once it has no members).
- `folder_judgment` and `folder_search`: `find-packs`'s stored answers and its search
  cache.

Tables are rebuilt in SQLite's documented order (create `<table>_new`, copy, drop,
rename) with foreign key enforcement off, as in 0005.

Downgrade dissolves every pack: each member gets a file entry carrying the pack's
product, and the pack's disposition is written to its `file.disposition`. The pack's
own entry and the rows keyed by it (evidence, text analysis, errors, review flags) go.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables keyed by `entry_id` (see 0005).
ENTRY_KEYED = (
    "google_search_result",
    "dtrpg_result",
    "rpggeek_result",
    "file_text_analysis",
    "error",
    "review_flag",
)
ENTRY_CHECK = (
    "(type = 'file' AND file_id IS NOT NULL AND pack_id IS NULL) OR "
    "(type = 'pack' AND pack_id IS NOT NULL AND file_id IS NULL)"
)


def _require_foreign_keys_off() -> None:
    """Dropping a table with enforcement on would cascade-delete its children."""
    enabled = op.get_bind().execute(sa.text("PRAGMA foreign_keys")).scalar()
    if enabled:
        raise RuntimeError("PRAGMA foreign_keys is on; this migration needs it off.")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _rebuild_entry(with_pack: bool) -> None:
    columns = [
        sa.Column("id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
    ]
    constraints: list[sa.Constraint] = [
        sa.ForeignKeyConstraint(["file_id"], ["file.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", name="uq_entry_file_id"),
    ]
    if with_pack:
        columns.append(sa.Column("pack_id", sa.Integer(), nullable=True))
        constraints += [
            sa.ForeignKeyConstraint(["pack_id"], ["pack.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("pack_id", name="uq_entry_pack_id"),
            sa.CheckConstraint(ENTRY_CHECK, name="ck_entry_one_item"),
        ]
    op.create_table("entry_new", *columns, *constraints)
    names = "id, created_at, updated_at, type, file_id, product_id"
    op.execute(f"INSERT INTO entry_new ({names}) SELECT {names} FROM entry ORDER BY id")
    op.drop_table("entry")
    op.rename_table("entry_new", "entry")
    op.create_index("ix_entry_product_id", "entry", ["product_id"], unique=False)


def upgrade() -> None:
    """Upgrade schema."""
    _require_foreign_keys_off()
    op.create_table(
        "pack",
        sa.Column("id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("root_id", sa.Integer(), nullable=False),
        sa.Column("original_root_path", sa.String(), nullable=False),
        sa.Column(
            "disposition",
            sa.String(length=16),
            server_default="unfiled",
            nullable=False,
        ),
        sa.Column("formation", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["root_id"], ["root.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pack_root_id", "pack", ["root_id"], unique=False)

    _rebuild_entry(with_pack=True)

    with op.batch_alter_table("file", recreate="always") as batch:
        batch.add_column(sa.Column("pack_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_file_pack_id_pack", "pack", ["pack_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_file_pack_id", ["pack_id"], unique=False)

    op.create_table(
        "folder_judgment",
        sa.Column("id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("root_id", sa.Integer(), nullable=False),
        sa.Column("folder", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("pack_id", sa.Integer(), nullable=True),
        sa.Column("judged_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pack_id"], ["pack.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["root_id"], ["root.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_id", "folder"),
    )
    for column in ("root_id", "outcome", "pack_id"):
        op.create_index(
            f"ix_folder_judgment_{column}", "folder_judgment", [column], unique=False
        )
    op.create_table(
        "folder_search",
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("query"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    _require_foreign_keys_off()
    # Dissolve packs: each member becomes a file entry with its pack's decision.
    op.execute(
        "INSERT INTO entry (created_at, updated_at, type, file_id, product_id) "
        "SELECT CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'file', f.id, pe.product_id "
        "FROM file f JOIN entry pe ON pe.pack_id = f.pack_id "
        "WHERE f.pack_id IS NOT NULL ORDER BY f.id"
    )
    op.execute(
        "UPDATE file SET disposition = "
        "(SELECT p.disposition FROM pack p WHERE p.id = file.pack_id) "
        "WHERE pack_id IS NOT NULL"
    )
    # Enforcement is off, so the cascade from a pack entry is done by hand.
    for table in ENTRY_KEYED:
        op.execute(
            f"DELETE FROM {table} WHERE entry_id IN "
            "(SELECT id FROM entry WHERE type = 'pack')"
        )
    op.execute("DELETE FROM entry WHERE type = 'pack'")

    for column in ("root_id", "outcome", "pack_id"):
        op.drop_index(f"ix_folder_judgment_{column}", table_name="folder_judgment")
    op.drop_table("folder_judgment")
    op.drop_table("folder_search")

    with op.batch_alter_table("file", recreate="always") as batch:
        batch.drop_index("ix_file_pack_id")
        batch.drop_constraint("fk_file_pack_id_pack", type_="foreignkey")
        batch.drop_column("pack_id")

    _rebuild_entry(with_pack=False)
    op.drop_index("ix_pack_root_id", table_name="pack")
    op.drop_table("pack")
