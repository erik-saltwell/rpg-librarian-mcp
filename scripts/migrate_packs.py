#!/usr/bin/env python3
"""One-time pack migration: bring a catalog to the pack schema and adopt filed packs.

Three separate steps, so the schema-only result can be validated before any adoption
writes, and so live data gets exactly the reviewed decisions of the rehearsal:

  1. `upgrade`  -- Alembic 0005 -> 0006 (`pack`, `folder_judgment`, `folder_search`,
                   `entry.pack_id`, `file.pack_id`). Changes no catalog content.
  2. `propose`  -- on a copy only: runs `find-packs`'s detection (gate, folder search,
                   model, lossless check) over every kept product's own folder below the
                   library's product lines, as a dry run, and writes the adoption list:
                   every proposed pack with its exact members, product, and disposition,
                   plus a review summary. Answers and searches are stored in the copy,
                   so a rerun (after `--limit`, or to rewrite the list) asks only about
                   folders not answered yet.
  3. `apply`    -- forms exactly the packs on a reviewed list, after checking that the
                   catalog still matches it; no search or model call. All or nothing, in
                   one transaction. A list that is already applied is a no-op.
                   `--check-only` reports the match without writing.

Validation is separate and independent:
`~/data/rpg_test_tools/pack_migration_validate.py`.
See `.work-items/pack-migration/` for the process.

Usage (with the rpg-librarian-mcp environment):

    uv run --project ~/proj/rpg-librarian-mcp/apps/rpg-librarian python \\
        ~/proj/rpg-librarian-mcp/scripts/migrate_packs.py upgrade --catalog COPY.db
    ... propose --catalog PROPOSAL-COPY.db --out LIST.json [--limit N] [--no-search]
    ... apply --catalog COPY.db --list LIST.json [--check-only]

The live catalog is refused unless `--live` is given (`upgrade`, `apply`); `propose`
never runs on it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rpg_librarian.config import load_env
from rpg_librarian.db import readonly_connection, session_scope, upgrade
from rpg_librarian.find_packs.adopt import (
    PLAN_FORMAT,
    PLAN_VERSION,
    apply_plan,
    check_source,
    propose,
)
from rpg_librarian.find_packs.judge import model_name

LIVE = Path("~/data/rpg-librarian/catalog.db").expanduser()
FROM_REVISION = "0005"
TO_REVISION = "0006"


def revision(catalog: Path) -> str:
    with readonly_connection(catalog) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def is_live(catalog: Path) -> bool:
    return LIVE.exists() and catalog.resolve().samefile(LIVE)


def guard(catalog: Path, *, live_allowed: bool, live: bool) -> Path:
    if not catalog.is_file():
        sys.exit(f"{catalog}: no such catalog")
    if is_live(catalog):
        if not live_allowed:
            sys.exit(f"{catalog} is the live catalog; this step only runs on a copy.")
        if not live:
            sys.exit(f"{catalog} is the live catalog; pass --live to run on it.")
    elif live:
        sys.exit(f"--live given, but {catalog} is not the live catalog.")
    return catalog.resolve()


def require_head(catalog: Path) -> None:
    current = revision(catalog)
    if current != TO_REVISION:
        sys.exit(
            f"{catalog} is at {current}; run `upgrade` first (needs {TO_REVISION})."
        )


def code_version() -> str:
    repo = Path(__file__).resolve().parent.parent
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{' + uncommitted changes' if dirty else ''}"


# -- upgrade ---------------------------------------------------------------------


def cmd_upgrade(args: argparse.Namespace) -> int:
    catalog = guard(args.catalog, live_allowed=True, live=args.live)
    current = revision(catalog)
    if current == TO_REVISION:
        print(f"{catalog} is already at {TO_REVISION}; nothing to do.")
        return 0
    if current != FROM_REVISION:
        sys.exit(
            f"{catalog} is at {current}; this migration starts from {FROM_REVISION}."
        )
    upgrade(catalog)
    print(f"{catalog}: {current} -> {revision(catalog)}")
    return 0


# -- propose ---------------------------------------------------------------------


def cmd_propose(args: argparse.Namespace) -> int:
    catalog = guard(args.catalog, live_allowed=False, live=False)
    require_head(catalog)
    if args.out.exists() and not args.overwrite:
        sys.exit(f"{args.out} exists; pass --overwrite to replace it.")
    load_env()
    with session_scope(catalog, migrate=False) as session:
        result = propose(session, limit=args.limit, no_search=args.no_search)
        adopter = result.adopter
        stats = adopter.stats
        plan = {
            "format": PLAN_FORMAT,
            "version": PLAN_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "proposed_on": str(catalog),
            "code": code_version(),
            "model": model_name(),
            "complete": stats.not_asked == 0
            and stats.stopped is None
            and not stats.errors,
            "packs": result.proposals,
        }
        review = _review(plan, adopter)
    args.out.write_text(json.dumps(plan, indent=1, ensure_ascii=False, default=str))
    review_path = args.out.with_suffix(".review.md")
    review_path.write_text(review)
    print(review.split("\n## Proposed packs")[0])
    print(f"list: {args.out}\nreview: {review_path}")
    if not plan["complete"]:
        print("warning: the list is incomplete (limit, stop, or errors); run again.")
    return 0


def _review(plan: dict[str, Any], adopter: Any) -> str:
    s = adopter.stats
    packs = plan["packs"]
    members = sum(len(p["members"]) for p in packs)
    by_type = Counter(p["product"]["type"] for p in packs)
    lines = [
        "# Pack adoption proposal",
        "",
        f"- proposed on: `{plan['proposed_on']}` at {plan['created_at']}",
        f"- code: {plan['code']}; model: {plan['model']}",
        f"- complete: {plan['complete']}",
        f"- model calls: {s.calls} (folders asked {s.folders_asked}, "
        f"stored answers reused {s.reused})",
        f"- searches: {s.searches} made, {s.searches_cached} cached, "
        f"{s.searches_skipped} skipped (generic name), {s.search_errors} failed"
        + (f"; searching off: {s.search_disabled}" if s.search_disabled else ""),
        f"- candidate product folders: {adopter.candidates}",
        f"- proposed packs: {len(packs)} with {members} member files",
        f"- proposed by type: {dict(sorted(by_type.items()))}",
        f"- left loose after the model said pack (mixed): {len(s.mixed)}",
        f"- invalid answers: {len(s.invalid)}; errors: {len(s.errors)}; "
        f"not asked: {s.not_asked}",
        "",
        "Folders under product lines that were not candidates or not asked:",
        "",
    ]
    for why, count in adopter.skipped.most_common():
        lines.append(f"- {why}: {count}")
    if s.stopped:
        lines.append(f"\nwarning: stopped early: {s.stopped}")
    answers = Counter()
    other: list[str] = []
    for (_root_id, folder), judgment in sorted(adopter.judgments.items()):
        answers[judgment.outcome.value] += 1
        if judgment.outcome.value in (
            "container",
            "no_packs",
            "mixed",
            "invalid",
            "error",
        ):
            other.append(
                f"| `{folder}` | {judgment.outcome.value} | "
                f"{(judgment.reason or '').replace('|', '/')} |"
            )
    lines += ["", f"Stored answers by outcome: {dict(sorted(answers.items()))}", ""]
    lines += [
        "## Proposed packs",
        "",
        "| Folder | Type | Members | Media | Reason |",
        "|---|---|---|---|---|",
    ]
    for p in packs:
        media = Counter(m["media_type"] or "unknown" for m in p["members"])
        reason = (p["reason"] or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| `{p['folder']}` | {p['product']['type']} | {len(p['members'])} | "
            f"{dict(media.most_common())} | {reason} |"
        )
    lines += [
        "",
        "## Asked, not proposed",
        "",
        "| Folder | Outcome | Reason |",
        "|---|---|---|",
    ]
    lines += other
    return "\n".join(lines) + "\n"


# -- apply -----------------------------------------------------------------------


def cmd_apply(args: argparse.Namespace) -> int:
    catalog = guard(args.catalog, live_allowed=True, live=args.live)
    require_head(catalog)
    plan = json.loads(args.list.read_text())
    if not plan.get("complete"):
        sys.exit(f"{args.list} is marked incomplete; finish the proposal first.")
    with session_scope(catalog, migrate=False) as session:
        check = check_source(session, plan)
        print(
            f"list: {len(plan['packs'])} pack(s); ready: {len(check.unapplied)}, "
            f"already applied: {len(check.applied)}, problems: {len(check.problems)}"
        )
        for problem in check.problems:
            print(f"  problem: {problem}")
        if check.state in ("mismatch", "partial"):
            print(
                f"REFUSED: catalog does not match the list ({check.state}); no writes."
            )
            return 1
        if check.state == "applied":
            print("Already applied exactly as listed; nothing to do.")
            return 0
        if args.check_only:
            print("Catalog matches the list; ready to apply (--check-only: no writes).")
            return 0
        applied = apply_plan(session, plan)
        session.flush()
        after = check_source(session, plan)
        if after.state != "applied":
            session.rollback()
            print(
                f"REFUSED: after applying, the check says {after.state}; rolled back."
            )
            for problem in after.problems[:20]:
                print(f"  problem: {problem}")
            return 1
    print(
        f"Applied: {applied.packs} pack(s), {applied.members} member file(s); "
        f"{applied.entries_removed} file entries removed with their evidence."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    steps = parser.add_subparsers(dest="step", required=True)
    up = steps.add_parser("upgrade", help="Alembic 0005 -> 0006 only.")
    pr = steps.add_parser("propose", help="Detect packs on a copy; write the list.")
    ap = steps.add_parser("apply", help="Form exactly the packs on a list.")
    for step in (up, pr, ap):
        step.add_argument("--catalog", type=Path, required=True)
    for step in (up, ap):
        step.add_argument("--live", action="store_true", help="Allow the live catalog.")
    pr.add_argument("--out", type=Path, required=True, help="The adoption list (JSON).")
    pr.add_argument("--overwrite", action="store_true")
    pr.add_argument("--limit", type=int, help="At most this many model calls.")
    pr.add_argument("--no-search", action="store_true", help="Make no Google searches.")
    ap.add_argument("--list", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    handler = {"upgrade": cmd_upgrade, "propose": cmd_propose, "apply": cmd_apply}
    sys.exit(handler[args.step](args))


if __name__ == "__main__":
    main()
