"""`find-packs`: form packs from folder evidence, a folder-name search, and an LLM.

Run after `scan` and before `enrich`. Per root, the folder tree is walked top-down, one
level at a time:

- A settled folder (no unfiled, eligible file below it) is skipped, and so is a folder
  that is already a pack's root: a pack is never re-judged.
- A folder with a stored answer and an unchanged fingerprint reuses it: `container`
  descends into its stored children; `no_packs`, `mixed`, and `invalid` stop there; a
  `pack` proposed by a dry run is formed without asking again. `error` is retried.
- A folder that fails the gate (too few files, or mostly documents), or that holds an
  existing pack below it, is not asked about; the walk descends into its children.
- The rest are asked about with their siblings in one model call each, after one cached
  Google search per folder name (skipped for generic names such as "Maps").

A `pack` answer is validated (no existing or newly formed pack overlaps it, at least one
eligible file) and formed only if no existing decision is lost: all its files unfiled,
or all filed to the same product with the same disposition, which the pack then takes.
Otherwise the folder is recorded as `mixed` and left as loose files. Every answer is
stored in `folder_judgment`; a formed pack keeps its evidence, and its folder search is
copied to its `google_search_result` so `enrich` does not search again.

`--dry-run` asks and stores answers and searches but forms nothing; a later run forms
the proposed packs without asking again while their folders are unchanged. `--limit`
caps the model calls. `--no-search` skips the searches.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from ..db import session_scope
from ..enrichment.base import FatalSourceError
from ..enrichment.google import serper_available, serper_search
from ..errors import UsageError
from ..find_packs.evidence import (
    SHOWN_CHILDREN,
    FolderNode,
    build_trees,
    eligible,
    fingerprint,
    passes_gate,
    search_query,
    summary,
    unsettled,
)
from ..find_packs.judge import FolderAnswer, judge
from ..membership import join
from ..model import (
    Disposition,
    Entry,
    EntryType,
    File,
    FolderJudgment,
    FolderOutcome,
    FolderSearch,
    GoogleSearchResult,
    Pack,
    PackFormation,
    Root,
)
from ..observability import log_call_fields
from ..services.pack_info import pack_views

BATCH = 10  # sibling folders per model call
_SHOWN_HITS = 5


@dataclass
class Stats:
    calls: int = 0
    folders_asked: int = 0
    reused: int = 0
    searches: int = 0
    searches_cached: int = 0
    searches_skipped: int = 0
    search_errors: int = 0
    not_asked: int = 0
    formed: list[tuple[int, str, str, int]] = field(default_factory=list)
    proposed: list[tuple[str, str, int]] = field(default_factory=list)
    mixed: list[tuple[str, str, str]] = field(default_factory=list)
    invalid: list[tuple[str, str, str]] = field(default_factory=list)
    errors: list[tuple[str, str, str]] = field(default_factory=list)
    search_disabled: str | None = None
    stopped: str | None = None


class Finder:
    def __init__(self, session: Session, args: argparse.Namespace) -> None:
        self.session = session
        self.limit: int | None = args.limit
        self.dry_run: bool = args.dry_run
        self.stats = Stats()
        if args.no_search:
            self.stats.search_disabled = "--no-search"
        elif (reason := serper_available()) is not None:
            self.stats.search_disabled = reason
        self.labels: dict[int, str] = {}
        self.decisions: dict[int, int | None] = {}  # loose file id -> product id
        self.pack_roots: set[tuple[int, str]] = set()
        self.judgments: dict[tuple[int, str], FolderJudgment] = {}
        self.claimed: set[int] = set()
        self.kept_products: set[int] = set()  # products given a kept pack this run
        self.searched: dict[str, tuple[str, list[dict[str, Any]]]] = {}

    # -- setup ---------------------------------------------------------------

    def load(self, roots: list[Root]) -> dict[int, FolderNode]:
        self.labels = {r.id: r.label or Path(r.path).name for r in roots if r.id}
        root_ids = list(self.labels)
        files = list(
            self.session.exec(select(File).where(col(File.root_id).in_(root_ids))).all()
        )
        self.decisions = {
            file_id: product_id
            for file_id, product_id in self.session.exec(
                select(col(Entry.file_id), col(Entry.product_id)).where(
                    col(Entry.file_id).is_not(None)
                )
            ).all()
            if file_id is not None
        }
        for view in pack_views(self.session).values():
            # A one-member pack's derived root is just that file's folder (a kept one
            # sits flat in its line folder), so only the original root counts then.
            if view.members >= 2:
                self.pack_roots.add((view.root_id, view.folder))
            self.pack_roots.add((view.pack.root_id, view.pack.original_root_path))
        self.judgments = {
            (j.root_id, j.folder): j
            for j in self.session.exec(
                select(FolderJudgment).where(col(FolderJudgment.root_id).in_(root_ids))
            ).all()
        }
        return build_trees(files)

    # -- the walk ------------------------------------------------------------

    def walk(self, top: FolderNode) -> None:
        queue: deque[tuple[FolderNode, list[FolderNode]]] = deque()
        queue.append((top, [top.children[n] for n in sorted(top.children)]))
        while queue:
            parent, children = queue.popleft()
            candidates: list[FolderNode] = []
            for node in children:
                verdict = self._visit(node)
                if verdict == "ask":
                    candidates.append(node)
                elif isinstance(verdict, list):
                    queue.append((node, verdict))
            for start in range(0, len(candidates), BATCH):
                self._ask(parent, candidates[start : start + BATCH], queue)

    def _children(
        self, node: FolderNode, names: list[str] | None = None
    ) -> list[FolderNode]:
        """The children to walk: all of them, or the named ones plus every one the
        model was not shown (a summary lists only the first `SHOWN_CHILDREN`), so a
        container with hundreds of releases is walked in full."""
        everything = sorted(node.children)
        if not names:
            return [node.children[n] for n in everything]
        unshown = [n for n in everything[SHOWN_CHILDREN:] if n not in names]
        return [node.children[n] for n in [*names, *unshown] if n in node.children]

    def _visit(self, node: FolderNode) -> str | list[FolderNode] | None:
        """ "ask", children to descend into, or None (nothing to do here)."""
        if not any(unsettled(f) for f in node.all_files()):
            return None
        if (node.root_id, node.path) in self.pack_roots:
            return None
        stored = self.judgments.get((node.root_id, node.path))
        if stored is not None and stored.fingerprint == fingerprint(node):
            outcome = stored.outcome
            if outcome is FolderOutcome.container:
                self.stats.reused += 1
                names = (stored.details or {}).get("descend_into") or None
                return self._children(node, names)
            if outcome in (
                FolderOutcome.no_packs,
                FolderOutcome.mixed,
                FolderOutcome.invalid,
            ):
                self.stats.reused += 1
                return None
            if outcome is FolderOutcome.pack:
                self.stats.reused += 1
                proposed = bool((stored.details or {}).get("proposed"))
                if stored.pack_id is None and proposed and not self.dry_run:
                    self._form(node, stored.reason or "", stored.evidence or {})
                return None
        if self._holds_pack(node) or not passes_gate(node):
            return self._children(node)
        return "ask"

    def _holds_pack(self, node: FolderNode) -> bool:
        return any(
            root_id == node.root_id and folder != node.path and node.below(folder)
            for root_id, folder in self.pack_roots
        )

    def _ask(
        self,
        parent: FolderNode,
        batch: list[FolderNode],
        queue: deque[tuple[FolderNode, list[FolderNode]]],
    ) -> None:
        if self.stats.stopped or (
            self.limit is not None and self.stats.calls >= self.limit
        ):
            self.stats.not_asked += len(batch)
            return
        summaries = {node.path: summary(node, self._search(node)) for node in batch}
        self.stats.calls += 1
        try:
            answers = judge(parent.path, list(summaries.values()))
        except FatalSourceError as error:
            self.stats.stopped = str(error)
            self.stats.not_asked += len(batch)
            return
        except Exception as error:
            for node in batch:
                self._record(
                    node,
                    FolderOutcome.error,
                    f"{type(error).__name__}: {error}",
                    {},
                    summaries[node.path],
                )
                self.stats.errors.append(
                    (self.labels[node.root_id], node.path, str(error)[:200])
                )
            self.session.commit()
            return
        self.stats.folders_asked += len(batch)
        by_folder: dict[str, FolderAnswer] = {a.folder.strip("/"): a for a in answers}
        for node in batch:
            answer = by_folder.get(node.path)
            evidence = summaries[node.path]
            if answer is None:
                self._record(
                    node, FolderOutcome.error, "the model gave no answer", {}, evidence
                )
                self.stats.errors.append(
                    (self.labels[node.root_id], node.path, "no answer")
                )
            elif answer.decision == "pack":
                self._form(node, answer.reason, evidence)
            elif answer.decision == "container":
                children = self._children(node, answer.descend_into or None)
                self._record(
                    node,
                    FolderOutcome.container,
                    answer.reason,
                    {"descend_into": [c.name for c in children]},
                    evidence,
                )
                queue.append((node, children))
            else:
                self._record(node, FolderOutcome.no_packs, answer.reason, {}, evidence)
        self.session.commit()

    # -- searching -----------------------------------------------------------

    def _search(self, node: FolderNode) -> dict[str, Any] | None:
        if self.stats.search_disabled:
            return None
        query = search_query(node)
        if query is None:
            self.stats.searches_skipped += 1
            return None
        key = query.casefold()
        cached = self.session.get(FolderSearch, key)
        if cached is not None:
            self.stats.searches_cached += 1
            results = cached.results
        else:
            try:
                results = serper_search(query)
            except FatalSourceError as error:
                self.stats.search_disabled = str(error)
                return None
            except Exception:
                self.stats.search_errors += 1
                return None
            self.session.add(FolderSearch(query=key, results=results))
            self.stats.searches += 1
        self.searched[node.path] = (query, results)
        return {
            "query": query,
            "hits": [
                {"title": hit.get("title"), "snippet": hit.get("snippet")}
                for hit in results[:_SHOWN_HITS]
            ],
        }

    # -- forming -------------------------------------------------------------

    def _form(self, node: FolderNode, reason: str, evidence: dict[str, Any]) -> None:
        """Validate a `pack` answer and form the pack losslessly, or record why not."""
        label = self.labels[node.root_id]
        files = [f for f in node.all_files() if eligible(f)]
        members = [f for f in node.all_files() if f.pack_id is not None]
        problem = None
        if members:
            problem = "it overlaps an existing pack"
        elif any(f.id in self.claimed for f in files):
            problem = "it overlaps a pack formed earlier in this run"
        elif not files:
            problem = "no file below it can be a member"
        if problem:
            self._record(
                node, FolderOutcome.invalid, problem, {"answer": reason}, evidence
            )
            self.stats.invalid.append((label, node.path, problem))
            return

        decisions = {
            (
                f.disposition,
                None
                if f.disposition is Disposition.unfiled
                else self.decisions.get(f.id or -1),
            )
            for f in files
        }
        conflict = None
        if len(decisions) > 1:
            conflict = (
                "its files are filed differently; forming it would lose a decision"
            )
        else:
            disposition, product_id = next(iter(decisions))
            if (
                disposition is Disposition.keep
                and product_id is not None
                and (
                    product_id in self.kept_products or self._has_kept_pack(product_id)
                )
            ):
                conflict = "its files' product already has a kept pack"
        if conflict:
            sample = sorted(
                {f"{d.value}:{p}" for d, p in decisions}  # disposition:product id
            )[:5]
            self._record(
                node,
                FolderOutcome.mixed,
                conflict,
                {"answer": reason, "decisions": sample},
                evidence,
            )
            self.stats.mixed.append((label, node.path, conflict))
            return
        disposition, product_id = next(iter(decisions))

        if self.dry_run:
            self._record(
                node,
                FolderOutcome.pack,
                reason,
                {"proposed": True, "members": len(files)},
                evidence,
            )
            self.stats.proposed.append((label, node.path, len(files)))
            return

        pack = Pack(
            root_id=node.root_id,
            original_root_path=node.path,
            disposition=disposition,
            formation=PackFormation.find_packs,
            reason=reason,
            evidence=evidence,
        )
        self.session.add(pack)
        self.session.flush()
        entry = Entry(type=EntryType.pack, pack_id=pack.id, product_id=product_id)
        self.session.add(entry)
        self.session.flush()
        for file in files:
            join(self.session, file, pack)
            if file.id is not None:
                self.claimed.add(file.id)
        if disposition is Disposition.keep and product_id is not None:
            self.kept_products.add(product_id)
        searched = self.searched.get(node.path)
        if searched is None and (evidence.get("search") or {}).get("query"):
            query = evidence["search"]["query"]
            cached = self.session.get(FolderSearch, query.casefold())
            searched = (query, cached.results) if cached is not None else None
        if searched is not None:
            assert entry.id is not None
            self.session.merge(
                GoogleSearchResult(
                    entry_id=entry.id, query=searched[0], results=searched[1]
                )
            )
        assert pack.id is not None and entry.id is not None
        self.pack_roots.add((node.root_id, node.path))
        self._record(
            node, FolderOutcome.pack, reason, {"members": len(files)}, evidence, pack.id
        )
        self.stats.formed.append((entry.id, label, node.path, len(files)))

    def _has_kept_pack(self, product_id: int) -> bool:
        return (
            self.session.exec(
                select(Entry.id)
                .join(Pack, col(Pack.id) == col(Entry.pack_id))
                .where(col(Entry.product_id) == product_id)
                .where(col(Pack.disposition) == Disposition.keep)
            ).first()
            is not None
        )

    def _record(
        self,
        node: FolderNode,
        outcome: FolderOutcome,
        reason: str,
        details: dict[str, Any],
        evidence: dict[str, Any],
        pack_id: int | None = None,
    ) -> None:
        key = (node.root_id, node.path)
        row = self.judgments.get(key)
        if row is None:
            row = FolderJudgment(
                root_id=node.root_id,
                folder=node.path,
                fingerprint="",
                outcome=outcome,
            )
            self.judgments[key] = row
        row.fingerprint = fingerprint(node)
        row.outcome = outcome
        row.reason = reason
        row.details = details or None
        row.evidence = evidence or None
        row.pack_id = pack_id
        row.judged_at = datetime.now(UTC)
        self.session.add(row)


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Identify packs below every registered root (or only `--root PATH`)."""
    if args.limit is not None and args.limit < 1:
        raise UsageError("--limit must be at least 1.")
    with session_scope(catalog_path) as session:
        roots = list(session.exec(select(Root).order_by(col(Root.id))).all())
        if args.root is not None:
            wanted = args.root.expanduser().resolve()
            roots = [r for r in roots if Path(r.path) == wanted]
            if not roots:
                raise UsageError(f"{wanted} is not a registered root.")
        finder = Finder(session, args)
        trees = finder.load(roots)
        for root in roots:
            tree = trees.get(root.id or -1)
            if tree is not None:
                finder.walk(tree)
        session.commit()
    _print(finder.stats, args.dry_run)
    log_call_fields(
        calls=finder.stats.calls,
        folders_asked=finder.stats.folders_asked,
        reused=finder.stats.reused,
        searches=finder.stats.searches,
        searches_cached=finder.stats.searches_cached,
        searches_skipped=finder.stats.searches_skipped,
        formed=len(finder.stats.formed),
        proposed=len(finder.stats.proposed),
        mixed=len(finder.stats.mixed),
        invalid=len(finder.stats.invalid),
        errors=len(finder.stats.errors),
        not_asked=finder.stats.not_asked,
        dry_run=args.dry_run,
    )
    return 0


def _print(s: Stats, dry_run: bool) -> None:
    print(
        f"asked the model {s.calls} time(s) about {s.folders_asked} folder(s); "
        f"reused {s.reused} stored answer(s)"
    )
    print(
        f"searches: {s.searches} made, {s.searches_cached} cached, "
        f"{s.searches_skipped} skipped (generic name), {s.search_errors} failed"
        + (f"; searching off: {s.search_disabled}" if s.search_disabled else "")
    )
    if dry_run:
        print(f"packs proposed (dry run, nothing formed): {len(s.proposed)}")
        for label, folder, members in s.proposed:
            print(f"  {label}:{folder}  ({members} files)")
    else:
        print(f"packs formed: {len(s.formed)}")
        for entry_id, label, folder, members in s.formed:
            print(f"  entry {entry_id}  {label}:{folder}  ({members} files)")
    for title, rows in (
        ("left as loose files (mixed)", s.mixed),
        ("invalid answers", s.invalid),
        ("errors (retried next run)", s.errors),
    ):
        if rows:
            print(f"{title}: {len(rows)}")
            for label, folder, why in rows:
                print(f"  {label}:{folder}: {why}")
    if s.not_asked:
        print(f"not asked yet: {s.not_asked} folder(s) (--limit reached); run again")
    if s.stopped:
        print(f"warning: stopped early: {s.stopped}")
