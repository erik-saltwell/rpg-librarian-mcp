"""Where a file belongs on the share: pure functions of the catalog's names and paths.

`target_relative_path` is the only place placement rules live. `reorganize` and the
pending-change count both reach it through `services.placement`, so nothing derived is
ever stored.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from sqlalchemy import func
from sqlmodel import Session, col, select

from .model import Disposition, Entry, File, Pack

# Characters SMB/Windows reject in a path component, plus control characters.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
_MAX_COMPONENT_LENGTH = 200  # well under the 255 SMB limit, leaving room for suffixes
TRASH_DIRNAME = ".trash"


def sanitize_filename(name: str, *, number: int | None = None) -> str:
    """Apply the library policy, preserving the extension and optional suffix.

    Unicode combining marks belonging to accented letters are retained too.
    The limit applies to UTF-8 bytes as well as UTF-16 units for portable components.
    """
    allowed = " -_.&$#@%^()[]"
    cleaned = (
        "".join(
            c if c in allowed or unicodedata.category(c)[0] in "LNM" else "-"
            for c in name
        )
        .strip()
        .rstrip(". ")
    )
    cleaned = cleaned or "_"
    stem, dot, ext = cleaned.rpartition(".")
    if not stem or not dot:
        stem, extension = cleaned, ""
    else:
        extension = dot + ext
    devices = _RESERVED | {f"{p}{n}" for p in ("COM", "LPT") for n in "¹²³"}
    if stem.split(".")[0].rstrip(" ").upper() in devices:
        stem = "_" + stem
    suffix = f" ({number})" if number is not None else ""
    if len(extension.encode("utf-8")) > 100:
        raise ValueError("Filename extension exceeds the portable length limit")
    while (
        len((stem + suffix + extension).encode("utf-8")) > _MAX_COMPONENT_LENGTH
        or len((stem + suffix + extension).encode("utf-16-le")) // 2
        > _MAX_COMPONENT_LENGTH
    ):
        stem = stem[:-1]
    return (stem.rstrip(". ") or "_") + suffix + extension


# Where each non-kept disposition is routed, under `<library>/.trash/`.
TRASH_BUCKETS: dict[Disposition, str] = {
    Disposition.duplicate: "duplicates",
    Disposition.superseded: "superseded",
    Disposition.discard: "discarded",
}


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
    drops the product to one and the survivor moves up into the line folder. The
    members of a kept pack of that product count too.
    """
    loose = (
        select(func.count())
        .select_from(File)
        .join(Entry, col(Entry.file_id) == col(File.id))
        .where(col(Entry.product_id) == product_id)
        .where(col(File.disposition) == Disposition.keep)
    )
    members = (
        select(func.count())
        .select_from(File)
        .join(Pack, col(Pack.id) == col(File.pack_id))
        .join(Entry, col(Entry.pack_id) == col(Pack.id))
        .where(col(Entry.product_id) == product_id)
        .where(col(Pack.disposition) == Disposition.keep)
    )
    return session.exec(loose).one() + session.exec(members).one()


def clean_subpath(path: PurePosixPath) -> PurePosixPath:
    """A kept path below a product folder, safe to join under it.

    Empty, `.`, `..`, and root components are dropped so the result can never climb
    out of the product folder. Folder names are sanitized like every other folder;
    the filename follows the library's filename policy.
    """
    parts = [p for p in path.parts if p not in {"", ".", "..", "/"}]
    if not parts:
        raise ValueError(f"no filename in {str(path)!r}")
    *folders, filename = parts
    return PurePosixPath(
        *(sanitize_name(f) for f in folders), sanitize_filename(filename)
    )


def target_relative_path(
    *,
    type_name: str,
    line_name: str,
    product_name: str,
    subpath: PurePosixPath,
    kept_count: int,
) -> PurePosixPath:
    """`<type>/<line>/<product>/<subpath>`, or `<type>/<line>/<filename>` for a
    single-file product, relative to the library root.

    A single-file product has no product folder: it sits directly in its line
    folder, and is promoted into a product folder when it gains a second file.
    `subpath` is the file's path below its product folder (see `services.placement`):
    usually just the filename, with the source's variant subfolders kept above it.
    """
    parts = [sanitize_name(type_name), sanitize_name(line_name)]
    if kept_count <= 1:
        return PurePosixPath(*parts, sanitize_filename(subpath.name))
    return PurePosixPath(*parts, sanitize_name(product_name)) / clean_subpath(subpath)


def trash_bucket_of(root_is_library: bool, relative_path: str) -> str | None:
    """The trash bucket a library-relative path already sits in, else None."""
    parts = PurePosixPath(relative_path).parts
    if root_is_library and len(parts) > 2 and parts[0] == TRASH_DIRNAME:
        return parts[1]
    return None


def desired_trash_path(
    bucket: str,
    *,
    root_id: int,
    root_path: str,
    root_is_library: bool,
    relative_path: str,
) -> PurePosixPath:
    """Where a non-kept file belongs, relative to the library root.

    The original relative path is preserved beneath the bucket so nothing collides,
    behind a `<root id>-<root folder name>` component so two dumps holding the same
    relative path stay apart. A file already inside `.trash/` only swaps its bucket,
    so the location is stable: applying this to its own result changes nothing.
    """
    parts = PurePosixPath(relative_path).parts
    if trash_bucket_of(root_is_library, relative_path) is not None:
        return PurePosixPath(
            TRASH_DIRNAME, bucket, *parts[2:-1], sanitize_filename(parts[-1])
        )
    origin = f"{root_id}-{sanitize_name(PurePosixPath(root_path).name)}"
    return PurePosixPath(
        TRASH_DIRNAME, bucket, origin, *parts[:-1], sanitize_filename(parts[-1])
    )
