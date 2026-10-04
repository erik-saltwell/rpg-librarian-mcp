"""The folder tree of the catalog, and what can be said about a folder without a model.

Everything here comes from the `file` table (paths, sizes, media types, dispositions),
so `find-packs` never walks the share. A folder's facts cover the files below it:

- *eligible* files can become members: present, not an automatic duplicate, not already
  in a pack;
- *unsettled* files are eligible and still unfiled: a folder with none is settled and
  never asked about;
- the *gate*: a folder is a pack candidate only when it has at least `MIN_FILES`
  eligible files and at least `MEDIA_SHARE` of them are not documents (a pack may hold
  a short license or readme, but four PDFs are never a pack);
- the *fingerprint* changes whenever a file below is added, removed, or resized, so a
  stored answer is reused only while the folder is unchanged.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlmodel import Session, col, select

from rpg_librarian_tools.files import MediaType

from ..enrichment.queries import folder_words, words_of
from ..model import Disposition, File
from ..paths import TRASH_DIRNAME

# Gate and search defaults (plan decision 10), tuned on fixtures and a catalog copy.
MIN_FILES = 3
MEDIA_SHARE = 0.8
# A folder named only like this is a section or a category, not a release: searching
# for "Maps" tells the model nothing, so no search is made for it.
GENERIC_NAMES = frozenset(
    {
        "3d", "art", "artwork", "assets", "audio", "battle maps", "battlemaps",
        "bonus", "bw", "color", "colour", "day", "download", "downloads", "extras",
        "files", "foundry", "fantasy grounds", "grid", "gridded", "gridless", "hd",
        "images", "jpg", "jpeg", "map", "maps", "minis", "miniatures", "misc",
        "models", "music", "night", "no grid", "other", "pdf", "pdfs", "png", "print",
        "roll20", "sd", "sfx", "sound effects", "stl", "stls", "textures", "tiles",
        "token", "tokens", "various", "vtt", "webp",
    }
)  # fmt: skip
# Sibling folder names that mark variants of the same files.
VARIANT_WORDS = (
    {"day", "night"},
    {"gridded", "gridless"},
    {"grid", "no grid"},
    {"grid", "nogrid"},
    {"color", "bw"},
    {"colour", "bw"},
    {"color", "greyscale"},
    {"color", "grayscale"},
    {"light", "dark"},
    {"hd", "sd"},
    {"png", "jpg"},
    {"png", "jpeg"},
    {"png", "webp"},
    {"print", "screen"},
)
_NUMBERED = re.compile(r"^(.*?)(\d+)$")
# Subfolders described to the model; a container's others are always walked.
SHOWN_CHILDREN = 20
_SHOWN_FILES = 8
_SHOWN_DOCUMENTS = 5


def is_document(file: File) -> bool:
    """A book or text: a PDF (but not an Illustrator `.ai` map) or a plain-text file."""
    if file.media_type is MediaType.text:
        return True
    return file.media_type is MediaType.pdf and not file.relative_path.lower().endswith(
        ".ai"
    )


@dataclass
class Decision:
    """A loose file's current filing, for lossless formation."""

    disposition: Disposition
    product_id: int | None


@dataclass
class FolderNode:
    root_id: int
    path: str  # relative to the root; "" is the root itself
    children: dict[str, FolderNode] = field(default_factory=dict)
    files: list[File] = field(default_factory=list)  # present files directly here

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    def all_files(self) -> Iterator[File]:
        yield from self.files
        for child in self.children.values():
            yield from child.all_files()

    def below(self, other: str) -> bool:
        """Whether root-relative folder `other` is this folder or inside it."""
        return not self.path or other == self.path or other.startswith(self.path + "/")


def build_trees(files: list[File]) -> dict[int, FolderNode]:
    """One tree per root from present files; the library's `.trash/` is left out."""
    roots: dict[int, FolderNode] = {}
    for file in files:
        if file.missing_since is not None:
            continue
        parts = PurePosixPath(file.relative_path).parent.parts
        if parts[:1] == (TRASH_DIRNAME,):
            continue
        node = roots.setdefault(file.root_id, FolderNode(file.root_id, ""))
        for depth, name in enumerate(parts, start=1):
            child = node.children.get(name)
            if child is None:
                child = FolderNode(file.root_id, "/".join(parts[:depth]))
                node.children[name] = child
            node = child
        node.files.append(file)
    return roots


def eligible(file: File) -> bool:
    return (
        file.missing_since is None
        and file.pack_id is None
        and file.disposition is not Disposition.duplicate
    )


def unsettled(file: File) -> bool:
    return eligible(file) and file.disposition is Disposition.unfiled


def fingerprint(node: FolderNode) -> str:
    digest = hashlib.sha256()
    for file in sorted(node.all_files(), key=lambda f: f.relative_path):
        digest.update(f"{file.relative_path}\x1f{file.size_bytes}\n".encode())
    return digest.hexdigest()


def folder_fingerprint(session: Session, root_id: int, folder: str) -> str:
    """`fingerprint` of a folder read straight from the catalog (same digest)."""
    statement = (
        select(File)
        .where(col(File.root_id) == root_id)
        .where(col(File.missing_since).is_(None))
    )
    if folder:
        prefix = folder.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        statement = statement.where(
            col(File.relative_path).like(prefix + "/%", escape="\\")
        )
    node = FolderNode(root_id, folder)
    node.files = [
        f
        for f in session.exec(statement).all()
        if PurePosixPath(f.relative_path).parts[:1] != (TRASH_DIRNAME,)
    ]
    return fingerprint(node)


def passes_gate(node: FolderNode) -> bool:
    files = [f for f in node.all_files() if eligible(f)]
    if len(files) < MIN_FILES:
        return False
    media = sum(1 for f in files if not is_document(f))
    return media / len(files) >= MEDIA_SHARE


def is_generic(name: str) -> bool:
    return words_of(name).casefold() in GENERIC_NAMES


def search_query(node: FolderNode) -> str | None:
    """The folder's words with its parent's, or None for a generic folder name."""
    if not node.path or is_generic(node.name):
        return None
    parent = PurePosixPath(node.path).parent
    folders = [node.name] if str(parent) == "." else [parent.name, node.name]
    return folder_words(folders) or None


def _media(file: File) -> str:
    return file.media_type.value if file.media_type else "unknown"


def numbered_runs(files: list[File]) -> list[dict[str, Any]]:
    """Names that differ only by a trailing number ("Goblin_001" … "Goblin_024")."""
    runs: Counter[str] = Counter()
    for file in files:
        stem = PurePosixPath(file.relative_path).stem
        match = _NUMBERED.match(stem)
        if match:
            runs[match.group(1).casefold() + "#" * len(match.group(2))] += 1
    return [
        {"pattern": pattern, "files": count}
        for pattern, count in runs.most_common(3)
        if count >= MIN_FILES
    ]


def variant_subfolders(node: FolderNode) -> list[list[str]]:
    """Child folders that look like variants of each other: named as known variants, or
    holding mostly the same file names."""
    stems = {
        name: {
            str(
                PurePosixPath(f.relative_path).relative_to(child.path).with_suffix("")
            ).casefold()
            for f in child.all_files()
        }
        for name, child in node.children.items()
    }
    names = sorted(stems)
    pairs: list[list[str]] = []
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            words = {words_of(first).casefold(), words_of(second).casefold()}
            a, b = stems[first], stems[second]
            overlap = len(a & b) / len(a | b) if a and b else 0.0
            if words in VARIANT_WORDS or (overlap >= 0.6 and len(a & b) >= 2):
                pairs.append([first, second])
    return pairs[:10]


def summary(node: FolderNode, search: dict[str, Any] | None) -> dict[str, Any]:
    """The evidence the model sees for one folder (and that a formed pack keeps)."""
    files = [f for f in node.all_files() if eligible(f)]
    documents = [f for f in files if is_document(f)]
    children = []
    for name in sorted(node.children)[:SHOWN_CHILDREN]:
        below = [f for f in node.children[name].all_files() if eligible(f)]
        children.append(
            {
                "name": name,
                "files": len(below),
                "media_types": dict(Counter(_media(f) for f in below)),
                "subfolders": len(node.children[name].children),
            }
        )
    return {
        "folder": node.path,
        "name": node.name,
        "files": len(files),
        "files_directly_here": sum(1 for f in node.files if eligible(f)),
        "media_types": dict(Counter(_media(f) for f in files)),
        "documents": [
            str(PurePosixPath(f.relative_path).relative_to(node.path))
            for f in documents[:_SHOWN_DOCUMENTS]
        ],
        "numbered_runs": numbered_runs(files),
        "variant_subfolders": variant_subfolders(node),
        "subfolders": children,
        "more_subfolders": max(0, len(node.children) - SHOWN_CHILDREN),
        "sample_files": [
            str(PurePosixPath(f.relative_path).relative_to(node.path))
            for f in sorted(files, key=lambda f: f.relative_path)[:_SHOWN_FILES]
        ],
        "search": search,
    }
