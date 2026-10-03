"""add the entry table

`entry` becomes the identity the tools, evidence, errors, and review flags use. Today
every entry is a file entry (`type = 'file'`, `file_id` set); later kinds add their own
nullable foreign key. A pure refactor: no catalog content changes.

- `entry` is seeded with one row per file, `id = file.id`, so every existing id stays
  valid, and takes over `file.product_id` for every file, whatever its disposition.
- `file` loses `product_id`, its index, and the `keep => product` CHECK;
  `update_product` enforces that rule, since a CHECK cannot span tables.
- `google_search_result`, `dtrpg_result`, `rpggeek_result`, `file_text_analysis`,
  `error`, and `review_flag` are rebuilt keyed by `entry_id`, with their foreign key on
  `entry (id)`. Each row is mapped through `entry.file_id`, not by assuming equal ids.
  The open-flag index is renamed to `ix_review_flag_open_entry_id`.
- `isbn_result`, `file_text`, `file_metadata`, and the media tables keep `file_id`.

SQLite cannot drop a column used by a CHECK, an index, and a foreign key, nor change a
foreign key, so tables are rebuilt in SQLite's documented order (create `<table>_new`,
copy, drop, rename), with foreign key enforcement off, as it is on Alembic's connection.

Downgrade reverses it; rows belonging to entries that are not files (none exist at this
revision) would be dropped.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVIDENCE_TABLES = ("dtrpg_result", "google_search_result", "rpggeek_result")
FILE_INDEXES = ("root_id", "disposition", "media_type", "sha256", "duplicate_of_id")


def _require_foreign_keys_off() -> None:
    """Dropping a table with enforcement on would cascade-delete its children."""
    enabled = op.get_bind().execute(sa.text("PRAGMA foreign_keys")).scalar()
    if enabled:
        raise RuntimeError("PRAGMA foreign_keys is on; this migration needs it off.")


def _swap(table: str) -> None:
    """Replace `table` with the already filled `<table>_new`."""
    op.drop_table(table)
    op.rename_table(f"{table}_new", table)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _evidence_columns(key: str) -> list[sa.Column]:
    return [
        sa.Column(key, sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    ]


def _file_columns(with_product: bool) -> list[sa.Column]:
    columns = [
        sa.Column("id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("root_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mtime", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column(
            "disposition",
            sa.String(length=16),
            server_default="unfiled",
            nullable=False,
        ),
    ]
    if with_product:
        columns.append(sa.Column("product_id", sa.Integer(), nullable=True))
    columns += [
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("missing_since", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("subpath", sa.String(), nullable=True),
    ]
    return columns


def _rebuild_file(with_product: bool) -> None:
    constraints: list[sa.Constraint] = [
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_id", "relative_path"),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["file.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["root_id"], ["root.id"]),
    ]
    if with_product:
        constraints += [
            sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
            sa.CheckConstraint(
                "disposition != 'keep' OR product_id IS NOT NULL",
                name="ck_file_keep_requires_product",
            ),
        ]
    op.create_table("file_new", *_file_columns(with_product), *constraints)
    # Every column but product_id, which comes back from `entry` on downgrade.
    names = ", ".join(c.name for c in _file_columns(with_product=False))
    if with_product:
        product = "(SELECT e.product_id FROM entry e WHERE e.file_id = file.id)"
        op.execute(
            f"INSERT INTO file_new ({names}, product_id) "
            f"SELECT {names}, {product} FROM file ORDER BY id"
        )
    else:
        op.execute(
            f"INSERT INTO file_new ({names}) SELECT {names} FROM file ORDER BY id"
        )
    _swap("file")
    columns = FILE_INDEXES + (("product_id",) if with_product else ())
    for column in columns:
        op.create_index(f"ix_file_{column}", "file", [column], unique=False)


def _rebuild_keyed(
    table: str, columns: list[sa.Column], to_entry: bool, *extra
) -> None:
    """Rebuild a per-item table keyed by `entry_id` (to_entry) or back by `file_id`."""
    new_key, target = ("entry_id", "entry") if to_entry else ("file_id", "file")
    op.create_table(
        f"{table}_new",
        *columns,
        sa.ForeignKeyConstraint([new_key], [f"{target}.id"], ondelete="CASCADE"),
        *extra,
    )
    rest = [f'"{c.name}"' for c in columns if c.name != new_key]  # "query" is a keyword
    mapped = (
        "(SELECT e.id FROM entry e WHERE e.file_id = t.file_id)"
        if to_entry
        else "(SELECT e.file_id FROM entry e WHERE e.id = t.entry_id)"
    )
    op.execute(
        f'INSERT INTO "{table}_new" ({new_key}, {", ".join(rest)}) '
        f"SELECT {mapped}, {', '.join(f't.{n}' for n in rest)} "
        f'FROM "{table}" t WHERE {mapped} IS NOT NULL'
    )
    _swap(table)


def _rebuild_all_keyed(to_entry: bool) -> None:
    key = "entry_id" if to_entry else "file_id"
    for table in EVIDENCE_TABLES:
        _rebuild_keyed(
            table, _evidence_columns(key), to_entry, sa.PrimaryKeyConstraint(key)
        )
    _rebuild_keyed(
        "file_text_analysis",
        [
            sa.Column(key, sa.Integer(), nullable=False),
            *_timestamps(),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("possible_system", sa.String(), nullable=True),
        ],
        to_entry,
        sa.PrimaryKeyConstraint(key),
    )
    _rebuild_keyed(
        "error",
        [
            sa.Column(key, sa.Integer(), nullable=False),
            sa.Column("stage", sa.String(length=32), nullable=False),
            sa.Column("error_text", sa.String(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
        ],
        to_entry,
        sa.PrimaryKeyConstraint(key, "stage"),
    )
    _rebuild_keyed(
        "review_flag",
        [
            sa.Column("id", sa.Integer(), nullable=False),
            *_timestamps(),
            sa.Column(key, sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolution_note", sa.String(), nullable=True),
        ],
        to_entry,
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        f"ix_review_flag_open_{key}",
        "review_flag",
        [key],
        unique=True,
        sqlite_where=sa.text("resolved_at IS NULL"),
    )


def upgrade() -> None:
    """Upgrade schema."""
    _require_foreign_keys_off()
    op.create_table(
        "entry",
        sa.Column("id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["file.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", name="uq_entry_file_id"),
    )
    op.create_index("ix_entry_product_id", "entry", ["product_id"], unique=False)
    op.execute(
        "INSERT INTO entry (id, created_at, updated_at, type, file_id, product_id) "
        "SELECT id, created_at, updated_at, 'file', id, product_id "
        "FROM file ORDER BY id"
    )
    _rebuild_all_keyed(to_entry=True)
    _rebuild_file(with_product=False)


def downgrade() -> None:
    """Downgrade schema."""
    _require_foreign_keys_off()
    _rebuild_file(with_product=True)
    _rebuild_all_keyed(to_entry=False)
    op.drop_index("ix_entry_product_id", table_name="entry")
    op.drop_table("entry")
