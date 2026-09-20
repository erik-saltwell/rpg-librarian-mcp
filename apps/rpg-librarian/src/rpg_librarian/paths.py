"""Where a file belongs on the share: one pure function of the catalog's names.

`target_relative_path` is the only place placement rules live. `reorganize` and the
pending-change count both call it, so nothing derived is ever stored.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from sqlalchemy import func
from sqlmodel import Session, col, select

from .model import Disposition, File

# Characters SMB/Windows reject in a path component, plus control characters.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
_MAX_COMPONENT_LENGTH = 200  # well under the 255 SMB limit, leaving room for suffixes
TRASH_DIRNAME = ".trash"


def sanitize_name(name: str) -> str:
    """Make a name safe as one path component.

    Illegal characters become `-`, surrounding whitespace and trailing dots are
    dropped, reserved Windows device names gain a trailing `_`, and the result is
    truncated. Never returns an empty string.
    """
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(". ")
    cleaned = cleaned[:_MAX_COMPONENT_LENGTH].rstrip(". ")
    if not cleaned:
        return "_"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned += "_"
    return cleaned


def folder_key(name: str) -> str:
    """The form used to detect two names that would share one folder.

    Two different names can sanitize to the same folder ("Foo: Bar" and "Foo- Bar"),
    and SMB shares are usually case-insensitive, so uniqueness is checked on this.
    """
    return sanitize_name(name).casefold()


def kept_file_count(session: Session, product_id: int) -> int:
    """How many files occupy a product's folder.

    Only `keep` files of that product count, so superseding one of two kept files
    drops the product to one and the survivor moves up into the line folder.
    """
    statement = (
        select(func.count())
        .select_from(File)
        .where(col(File.product_id) == product_id)
        .where(col(File.disposition) == Disposition.keep)
    )
    return session.exec(statement).one()


def target_relative_path(
    *,
    type_name: str,
    line_name: str,
    product_name: str,
    filename: str,
    kept_count: int,
) -> PurePosixPath:
    """`<type>/<line>/[<product>/]<filename>`, relative to the library root.

    A single-file product has no product folder: it sits directly in its line
    folder, and is promoted into a product folder when it gains a second file.
    """
    parts = [sanitize_name(type_name), sanitize_name(line_name)]
    if kept_count > 1:
        parts.append(sanitize_name(product_name))
    return PurePosixPath(*parts, filename)
