"""Adopt already-filed products as packs: the one-time pack migration of a catalog.

`find-packs` only asks about folders with unfiled files, so a catalog filed before
packs existed holds no candidates. Adoption runs the same detection over filed product
folders, in two separate steps (see `scripts/migrate_packs.py`):

- `propose` walks each product line folder of the library and judges its child
  folders with `find-packs`'s gate, folder search, model, and lossless check, as a dry
  run: nothing is formed. A folder is a candidate only when it is a kept product's own
  folder (`<type>/<line>/<product>/`), every eligible file below it is filed `keep` to
  that product, the product has no kept file outside it, and no file has an open review
  flag or an error. Container and no-pack answers are recorded but not descended into:
  a product's subfolder is never a pack of its own. The result is an adoption list of
  every proposed pack with its exact members.
- `apply_plan` forms exactly the packs on a reviewed list, after checking that the
  catalog still matches it, with no search or model call. A member keeps its stored
  subpath, so no file's destination changes.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlmodel import Session, col, select

from ..commands.find_packs import BATCH, Finder
from ..membership import join
from ..model import (
    Disposition,
    Entry,
    EntryType,
    Error,
    File,
    FolderJudgment,
    FolderOutcome,
    FolderSearch,
    GoogleSearchResult,
    Pack,
    PackFormation,
    Product,
    ProductLine,
    ProductType,
    ReviewFlag,
    Root,
    RootKind,
)
from ..model.core import utc_now
from ..paths import TRASH_DIRNAME, target_relative_path
from .evidence import FolderNode, eligible, fingerprint, folder_fingerprint, passes_gate

PLAN_FORMAT = "rpg-librarian pack adoption list"
PLAN_VERSION = 1


def product_folder(type_name: str, line_name: str, product_name: str) -> str:
    """A kept product's own folder, relative to the library: placement's own rule."""
    path = target_relative_path(
        type_name=type_name,
        line_name=line_name,
        product_name=product_name,
        subpath=PurePosixPath("x"),
        kept_count=2,
    )
    return str(path.parent)


def _product_names(session: Session) -> dict[int, tuple[str, str, str]]:
    return {
        product.id: (product_type.name, line.name, product.name)
        for product, line, product_type in session.exec(
            select(Product, ProductLine, ProductType)
            .join(ProductLine, col(ProductLine.id) == col(Product.product_line_id))
            .join(ProductType, col(ProductType.id) == col(ProductLine.product_type_id))
        ).all()
        if product.id is not None
    }


def _blocked_entries(session: Session) -> set[int]:
    """Entries with an open review flag or an error: open work adoption would lose."""
    flagged = session.exec(
        select(ReviewFlag.entry_id).where(col(ReviewFlag.resolved_at).is_(None))
    ).all()
    errored = session.exec(select(Error.entry_id)).all()
    return {*flagged, *errored}


# -- proposing -------------------------------------------------------------------


class Adopter(Finder):
    """`find-packs` over filed product folders, as a dry run that collects proposals."""

    def __init__(self, session: Session, *, limit: int | None, no_search: bool) -> None:
        super().__init__(
            session,
            argparse.Namespace(limit=limit, dry_run=True, no_search=no_search),
        )
        self.names: dict[int, tuple[str, str, str]] = {}
        self.folders: dict[int, str] = {}  # product id -> its own folder
        self.entry_ids: dict[int, int] = {}  # loose file id -> entry id
        self.kept_files: dict[int, set[int]] = defaultdict(set)  # product -> files
        self.blocked: set[int] = set()  # file ids with open work on their entry
        self.root_paths: dict[int, str] = {}
        self.skipped: Counter[str] = Counter()
        self.candidates = 0
        self.proposals: list[dict[str, Any]] = []

    def load(self, roots: list[Root]) -> dict[int, FolderNode]:
        trees = super().load(roots)
        self.root_paths = {r.id: r.path for r in roots if r.id is not None}
        self.names = _product_names(self.session)
        self.folders = {
            product_id: product_folder(*names)
            for product_id, names in self.names.items()
        }
        blocked_entries = _blocked_entries(self.session)
        for file, entry in self.session.exec(
            select(File, Entry).join(Entry, col(Entry.file_id) == col(File.id))
        ).all():
            assert file.id is not None and entry.id is not None
            self.entry_ids[file.id] = entry.id
            if entry.id in blocked_entries:
                self.blocked.add(file.id)
            if (
                file.disposition is Disposition.keep
                and file.missing_since is None
                and entry.product_id is not None
            ):
                self.kept_files[entry.product_id].add(file.id)
        return trees

    def walk(self, top: FolderNode) -> None:
        """Ask about the child folders of each product line folder, line by line."""
        for type_name in sorted(top.children):
            type_node = top.children[type_name]
            for line_name in sorted(type_node.children):
                line = type_node.children[line_name]
                candidates = [
                    node for node in self._children(line) if self._visit(node) == "ask"
                ]
                for start in range(0, len(candidates), BATCH):
                    # A container answer is recorded but not followed: the queue is
                    # dropped, because a product's subfolder is never a pack.
                    self._ask(line, candidates[start : start + BATCH], deque())

    def _skip(self, why: str) -> None:
        self.skipped[why] += 1

    def _visit(self, node: FolderNode) -> str | list[FolderNode] | None:
        """ "ask" for a candidate that passes the gate, else None."""
        if (node.root_id, node.path) in self.pack_roots or self._holds_pack(node):
            self._skip("already a pack, or holds one")
            return None
        files = [f for f in node.all_files() if eligible(f)]
        if not files:
            self._skip("no eligible files")
            return None
        if any(f.disposition is not Disposition.keep for f in files):
            self._skip("not every file is kept")
            return None
        products = {self.decisions.get(f.id or -1) for f in files}
        if len(products) != 1 or None in products:
            self._skip("files of several products")
            return None
        product_id = next(iter(products))
        assert product_id is not None
        if self.folders.get(product_id) != node.path:
            self._skip("not the product's own folder")
            return None
        if not self.kept_files[product_id] <= {f.id for f in files}:
            self._skip("the product has kept files elsewhere")
            return None
        if any(f.id in self.blocked for f in files):
            self._skip("open review flag or error")
            return None
        self.candidates += 1
        stored = self.judgments.get((node.root_id, node.path))
        if stored is not None and stored.fingerprint == fingerprint(node):
            self.stats.reused += 1
            if stored.outcome is FolderOutcome.pack:
                self._form(node, stored.reason or "", stored.evidence or {})
            elif stored.outcome is FolderOutcome.error:
                return "ask" if passes_gate(node) else None
            return None
        if not passes_gate(node):
            self._skip("fails the media gate")
            return None
        return "ask"

    def _form(self, node: FolderNode, reason: str, evidence: dict[str, Any]) -> None:
        proposed = len(self.stats.proposed)
        super()._form(node, reason, evidence)  # a dry run: validates and records only
        if len(self.stats.proposed) > proposed:
            self.proposals.append(self._proposal(node, reason, evidence))

    def _proposal(
        self, node: FolderNode, reason: str, evidence: dict[str, Any]
    ) -> dict[str, Any]:
        files = sorted(
            (f for f in node.all_files() if eligible(f)), key=lambda f: f.relative_path
        )
        product_id = self.decisions[files[0].id or -1]
        assert product_id is not None
        type_name, line_name, product_name = self.names[product_id]
        search = None
        query = (evidence.get("search") or {}).get("query")
        searched = self.searched.get(node.path)
        if searched is not None:
            search = {"query": searched[0], "results": searched[1]}
        elif query:
            cached = self.session.get(FolderSearch, query.casefold())
            if cached is not None:
                search = {"query": query, "results": cached.results}
        return {
            "root_id": node.root_id,
            "root_path": self.root_paths[node.root_id],
            "folder": node.path,
            "fingerprint": fingerprint(node),
            "disposition": Disposition.keep.value,
            "product_id": product_id,
            "product": {"type": type_name, "line": line_name, "name": product_name},
            "reason": reason,
            "evidence": evidence,
            "search": search,
            "members": [
                {
                    "file_id": f.id,
                    "entry_id": self.entry_ids[f.id or -1],
                    "relative_path": f.relative_path,
                    "size_bytes": f.size_bytes,
                    "mtime": f.mtime,
                    "sha256": f.sha256,
                    "media_type": f.media_type.value if f.media_type else None,
                    "disposition": f.disposition.value,
                    "subpath": f.subpath,
                }
                for f in files
            ],
        }


@dataclass
class Proposed:
    proposals: list[dict[str, Any]]
    adopter: Adopter


def propose(session: Session, *, limit: int | None, no_search: bool) -> Proposed:
    """Judge every candidate product folder of the library roots; form nothing."""
    roots = list(
        session.exec(
            select(Root)
            .where(col(Root.kind) == RootKind.library)
            .order_by(col(Root.id))
        ).all()
    )
    adopter = Adopter(session, limit=limit, no_search=no_search)
    trees = adopter.load(roots)
    for root in roots:
        tree = trees.get(root.id or -1)
        if tree is not None:
            adopter.walk(tree)
    session.commit()
    adopter.proposals.sort(key=lambda p: (p["root_id"], p["folder"]))
    return Proposed(adopter.proposals, adopter)


# -- checking a list against a catalog -------------------------------------------


@dataclass
class SourceCheck:
    """How a catalog stands against an adoption list."""

    unapplied: list[str] = field(default_factory=list)  # folders ready to adopt
    applied: list[str] = field(
        default_factory=list
    )  # folders already adopted as listed
    problems: list[str] = field(default_factory=list)

    @property
    def state(self) -> str:
        if self.problems:
            return "mismatch"
        if self.unapplied and self.applied:
            return "partial"
        return "applied" if self.applied else "unapplied"


def _files_below(session: Session, root_id: int, folder: str) -> list[File]:
    prefix = folder.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return [
        f
        for f in session.exec(
            select(File)
            .where(col(File.root_id) == root_id)
            .where(col(File.relative_path).like(prefix + "/%", escape="\\"))
        ).all()
        if PurePosixPath(f.relative_path).parts[:1] != (TRASH_DIRNAME,)
    ]


def check_source(session: Session, plan: dict[str, Any]) -> SourceCheck:
    """Whether every listed pack is ready to adopt exactly as listed, or already is."""
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        return SourceCheck(problems=["not a pack adoption list of a known version"])
    check = SourceCheck()
    names = _product_names(session)
    blocked = _blocked_entries(session)
    roots = {r.id: r for r in session.exec(select(Root)).all()}
    seen_products: set[int] = set()
    for item in plan["packs"]:
        where = f"{item['root_path']}:{item['folder']}"
        problems: list[str] = []
        root = roots.get(item["root_id"])
        product_id = item["product_id"]
        if root is None or root.path != item["root_path"]:
            problems.append("its root is not registered under that id")
        elif root.kind is not RootKind.library:
            problems.append("its root is not the library")
        if product_id in seen_products:
            problems.append("the list has another pack of the same product")
        seen_products.add(product_id)
        product = item["product"]
        if names.get(product_id) != (product["type"], product["line"], product["name"]):
            problems.append("the product's type, line, or name changed")
        listed = {m["file_id"]: m for m in item["members"]}
        below = _files_below(session, item["root_id"], item["folder"])
        present = [f for f in below if f.missing_since is None]
        pack = session.exec(
            select(Pack)
            .where(col(Pack.root_id) == item["root_id"])
            .where(col(Pack.original_root_path) == item["folder"])
        ).first()
        if pack is None:
            problems += _unapplied_problems(
                session, item, present, listed, names, blocked
            )
            target = check.unapplied
        else:
            problems += _applied_problems(session, item, pack, listed)
            target = check.applied
        if problems:
            check.problems += [f"{where}: {p}" for p in problems]
        else:
            target.append(where)
    return check


def _unapplied_problems(
    session: Session,
    item: dict[str, Any],
    present: list[File],
    listed: dict[int, dict[str, Any]],
    names: dict[int, tuple[str, str, str]],
    blocked: set[int],
) -> list[str]:
    problems: list[str] = []
    product_id = item["product_id"]
    node = FolderNode(item["root_id"], item["folder"])
    node.files = present
    if fingerprint(node) != item["fingerprint"]:
        problems.append("the folder's files changed (fingerprint differs)")
    members = [f for f in present if eligible(f)]
    if {f.id for f in members} != set(listed):
        problems.append(
            f"its eligible files differ from the list ({len(members)} here, "
            f"{len(listed)} listed)"
        )
    if any(f.pack_id is not None for f in present):
        problems.append("a file below it is already in a pack")
    entries = {
        e.file_id: e
        for e in session.exec(
            select(Entry).where(col(Entry.file_id).in_([f.id for f in members]))
        ).all()
    }
    for file in members:
        member = listed.get(file.id or -1)
        if member is None:
            continue
        entry = entries.get(file.id)
        actual = {
            "relative_path": file.relative_path,
            "size_bytes": file.size_bytes,
            "mtime": file.mtime,
            "sha256": file.sha256,
            "disposition": file.disposition.value,
            "subpath": file.subpath,
            "entry_id": entry.id if entry else None,
        }
        changed = sorted(k for k, v in actual.items() if member[k] != v)
        if changed:
            problems.append(f"{file.relative_path}: changed {', '.join(changed)}")
        if entry is None or entry.product_id != product_id:
            problems.append(f"{file.relative_path}: no longer filed to the product")
        elif entry.id in blocked:
            problems.append(f"{file.relative_path}: has an open review flag or error")
    kept_elsewhere = session.exec(
        select(File.id)
        .join(Entry, col(Entry.file_id) == col(File.id))
        .where(col(Entry.product_id) == product_id)
        .where(col(File.disposition) == Disposition.keep)
        .where(col(File.missing_since).is_(None))
    ).all()
    if not set(kept_elsewhere) <= set(listed):
        problems.append("the product has kept files outside the folder")
    kept_pack = session.exec(
        select(Pack.id)
        .join(Entry, col(Entry.pack_id) == col(Pack.id))
        .where(col(Entry.product_id) == product_id)
        .where(col(Pack.disposition) == Disposition.keep)
    ).first()
    if kept_pack is not None:
        problems.append("the product already has a kept pack")
    if product_id in names and product_folder(*names[product_id]) != item["folder"]:
        problems.append("the folder is no longer the product's own folder")
    return problems


def _applied_problems(
    session: Session, item: dict[str, Any], pack: Pack, listed: dict[int, Any]
) -> list[str]:
    problems: list[str] = []
    entry = session.exec(select(Entry).where(col(Entry.pack_id) == pack.id)).first()
    if entry is None or entry.product_id != item["product_id"]:
        problems.append("a pack is here, but not of the listed product")
    if pack.disposition.value != item["disposition"]:
        problems.append("a pack is here, with a different disposition")
    members = session.exec(select(File).where(col(File.pack_id) == pack.id)).all()
    if {f.id for f in members} != set(listed):
        problems.append("a pack is here, with different members")
    for file in members:
        member = listed.get(file.id or -1)
        if member is not None and file.subpath != member["subpath"]:
            problems.append(f"{file.relative_path}: member's subpath differs")
    return problems


# -- applying --------------------------------------------------------------------


@dataclass
class Applied:
    packs: int
    members: int
    entries_removed: int


def apply_plan(session: Session, plan: dict[str, Any]) -> Applied:
    """Form every pack on a checked, unapplied list; the caller commits."""
    packs = members = 0
    for item in plan["packs"]:
        pack = Pack(
            root_id=item["root_id"],
            original_root_path=item["folder"],
            disposition=Disposition(item["disposition"]),
            formation=PackFormation.find_packs,
            reason=item["reason"],
            evidence=item["evidence"],
        )
        session.add(pack)
        session.flush()
        assert pack.id is not None
        entry = Entry(
            type=EntryType.pack, pack_id=pack.id, product_id=item["product_id"]
        )
        session.add(entry)
        session.flush()
        assert entry.id is not None
        for file in _members(session, (m["file_id"] for m in item["members"])):
            subpath = file.subpath
            join(session, file, pack)
            file.subpath = subpath  # placed exactly where it is filed now
            session.add(file)
            members += 1
        if item["search"] is not None:
            session.add(
                GoogleSearchResult(
                    entry_id=entry.id,
                    query=item["search"]["query"],
                    results=item["search"]["results"],
                )
            )
        _record_judgment(session, item, pack.id)
        session.flush()
        packs += 1
    return Applied(packs=packs, members=members, entries_removed=members)


def _members(session: Session, file_ids: Iterable[int]) -> list[File]:
    wanted = list(file_ids)
    files = {
        f.id: f
        for f in session.exec(select(File).where(col(File.id).in_(wanted))).all()
    }
    return [files[file_id] for file_id in wanted]


def _record_judgment(session: Session, item: dict[str, Any], pack_id: int) -> None:
    row = session.exec(
        select(FolderJudgment)
        .where(col(FolderJudgment.root_id) == item["root_id"])
        .where(col(FolderJudgment.folder) == item["folder"])
    ).first()
    if row is None:
        row = FolderJudgment(
            root_id=item["root_id"],
            folder=item["folder"],
            fingerprint="",
            outcome=FolderOutcome.pack,
        )
    row.fingerprint = folder_fingerprint(session, item["root_id"], item["folder"])
    row.outcome = FolderOutcome.pack
    row.reason = item["reason"]
    row.details = {"members": len(item["members"]), "adopted": True}
    row.evidence = item["evidence"] or None
    row.pack_id = pack_id
    row.judged_at = utc_now()
    session.add(row)
