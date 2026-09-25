"""add file.subpath

A kept file's path below its product folder, filename included, stored once its
product has moved so that later runs of `reorganize` never re-derive it.

Backfill: every kept file already in its product's place in the library gets the path
it has there. A multi-file product's file inside `<type>/<line>/<product>/` gets the
path below that folder; a single-file product's file directly in `<type>/<line>/` gets
its filename. Everything else (files in a staging root, or not yet where they belong)
stays NULL and is worked out by the next `reorganize` as before. No file moves.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-25 18:00:00.000000

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A frozen copy of `rpg_librarian.paths.sanitize_name` as of this revision, so the
# backfill does not change if that function does.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
_MAX_COMPONENT_LENGTH = 200


def _sanitize_name(name: str) -> str:
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(". ")
    cleaned = cleaned[:_MAX_COMPONENT_LENGTH].rstrip(". ")
    if not cleaned:
        return "_"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned += "_"
    return cleaned


def _backfill() -> None:
    bind = op.get_bind()
    folders = {
        product_id: [_sanitize_name(n).casefold() for n in (type_, line, product)]
        for product_id, type_, line, product in bind.execute(
            sa.text(
                "SELECT p.id, t.name, l.name, p.name FROM product p "
                "JOIN product_line l ON l.id = p.product_line_id "
                "JOIN product_type t ON t.id = l.product_type_id"
            )
        )
    }
    kept_counts = {
        product_id: count
        for product_id, count in bind.execute(
            sa.text(
                "SELECT product_id, count(*) FROM file "
                "WHERE disposition = 'keep' AND missing_since IS NULL "
                "GROUP BY product_id"
            )
        )
    }
    updates = []
    for file_id, product_id, relative_path in bind.execute(
        sa.text(
            "SELECT f.id, f.product_id, f.relative_path FROM file f "
            "JOIN root r ON r.id = f.root_id "
            "WHERE r.kind = 'library' AND f.disposition = 'keep' "
            "AND f.missing_since IS NULL AND f.product_id IS NOT NULL"
        )
    ):
        folder = folders.get(product_id)
        if folder is None:
            continue
        parts = relative_path.split("/")
        lowered = [p.casefold() for p in parts]
        if kept_counts.get(product_id, 0) <= 1:
            if len(parts) == 3 and lowered[:2] == folder[:2]:
                updates.append({"id": file_id, "subpath": parts[2]})
        elif len(parts) > 3 and lowered[:3] == folder:
            updates.append({"id": file_id, "subpath": "/".join(parts[3:])})
    if updates:
        bind.execute(
            sa.text("UPDATE file SET subpath = :subpath WHERE id = :id"), updates
        )


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("file", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subpath", sa.String(), nullable=True))
    _backfill()


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("file", schema=None) as batch_op:
        batch_op.drop_column("subpath")
