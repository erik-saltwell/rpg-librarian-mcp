from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from .commands import (
    add_source,
    enrich,
    find_packs,
    init,
    reorganize,
    sanitize_filenames,
    scan,
    serve,
    tools,
)
from .config import load_env, resolve_catalog_path
from .enrichment.registry import SOURCES
from .errors import UsageError
from .model import ProcessingStage
from .observability import CallTracker, configure_wide_event_logs

Handler = Callable[[argparse.Namespace, Path], int]

_VERBS = {
    "init": "Create the catalog and register the library root.",
    "add-source": "Register a staging root (a dump folder).",
    "scan": "Walk roots and record files, hashes, and metadata.",
    "find-packs": "Identify packs (map packs, token sets, ...) with an LLM.",
    "enrich": "Look up external evidence and extract with an LLM.",
    "update-product": "Record a judgment about entries (the MCP writer).",
    "clear-errors": "Clear recorded errors (all, or only some stages).",
    "report-entry": "Everything known about one entry.",
    "report-product": "One product with its files.",
    "report-line": "One product line with its products.",
    "report-pack": "One pack with every subfolder and member file.",
    "create-pack": "Make the files below a folder one pack, by hand.",
    "add-to-pack": "Add a file, or a folder's files, to a pack.",
    "remove-from-pack": "Take a file, or a folder's files, out of a pack.",
    "list-unfiled": "The worklist: folders and files not yet filed.",
    "list-types": "Product types with counts.",
    "list-lines": "Product lines with aliases.",
    "reorganize": "Make the share match the catalog.",
    "sanitize-filenames": "Preview or apply library filename cleanup.",
    "serve": "Run the MCP server on stdio.",
}


def _not_implemented(args: argparse.Namespace, catalog_path: Path) -> int:
    print(
        f"{args.command}: not implemented yet (catalog: {catalog_path})",
        file=sys.stderr,
    )
    return 2


_HANDLERS: dict[str, Handler] = {
    "init": init.run,
    "add-source": add_source.run,
    "scan": scan.run,
    "find-packs": find_packs.run,
    "enrich": enrich.run,
    "update-product": tools.update_product,
    "clear-errors": tools.clear_errors,
    "report-entry": tools.report_entry,
    "report-product": tools.report_product,
    "report-line": tools.report_line,
    "report-pack": tools.report_pack,
    "create-pack": tools.create_pack,
    "add-to-pack": tools.add_to_pack,
    "remove-from-pack": tools.remove_from_pack,
    "list-unfiled": tools.list_unfiled,
    "list-types": tools.list_types,
    "list-lines": tools.list_lines,
    "reorganize": reorganize.run,
    "sanitize-filenames": sanitize_filenames.run,
    "serve": serve.run,
}


def build_parser() -> argparse.ArgumentParser:
    # --catalog lives on each subparser, not the top-level parser: argparse lets a
    # subparser's default override a value set before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--catalog",
        type=Path,
        help="Catalog file (default: $RPG_LIBRARIAN_CATALOG or ./catalog.db).",
    )

    parser = argparse.ArgumentParser(
        prog="rpg-librarian",
        description="Organize RPG content on a network share.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verbs = {
        name: subparsers.add_parser(name, help=help_text, parents=[common])
        for name, help_text in _VERBS.items()
    }
    verbs["init"].add_argument(
        "--library", type=Path, required=True, help="The library root directory."
    )
    verbs["add-source"].add_argument(
        "path", type=Path, help="The staging (dump) directory to register."
    )
    verbs["add-source"].add_argument("--label", help="A display name for the root.")
    verbs["enrich"].add_argument(
        "--source",
        action="append",
        choices=list(SOURCES),
        help="Run only this source (repeatable). Default: all.",
    )
    verbs["enrich"].add_argument(
        "--limit", type=int, help="At most this many files per source."
    )
    verbs["enrich"].add_argument(
        "--force",
        action="store_true",
        help="Refetch files a source has already covered.",
    )
    up = verbs["update-product"]
    up.add_argument(
        "entry_ids", type=int, nargs="+", help="Ids of the entries to update."
    )
    up.add_argument(
        "--disposition", choices=["keep", "superseded", "discard", "unfiled"]
    )
    up.add_argument("--type", dest="product_type")
    up.add_argument("--line", dest="product_line")
    up.add_argument("--product")
    up.add_argument("--create-line", action="store_true")
    up.add_argument("--create-type", action="store_true")
    up.add_argument("--alias", action="append", help="An alias for the line.")
    up.add_argument("--review-flag", help="Defer with this reason instead of filing.")
    up.add_argument("--note", help="Why, when this resolves an open review flag.")
    for field in ("publisher", "year", "artists", "description"):
        up.add_argument(f"--{field}")
    verbs["clear-errors"].add_argument(
        "--stage",
        action="append",
        choices=[stage.value for stage in ProcessingStage],
        help="Clear only this stage's errors (repeatable). Default: every error.",
    )
    verbs["report-entry"].add_argument("entry_id", type=int)
    verbs["report-pack"].add_argument("entry_id", type=int, help="The pack's entry id.")
    cp = verbs["create-pack"]
    cp.add_argument("folder", help="The folder, relative to its root.")
    cp.add_argument("--root-id", type=int)
    cp.add_argument(
        "--disposition", choices=["keep", "superseded", "discard", "unfiled"]
    )
    cp.add_argument("--type", dest="product_type")
    cp.add_argument("--line", dest="product_line")
    cp.add_argument("--product")
    cp.add_argument("--create-line", action="store_true")
    cp.add_argument("--create-type", action="store_true")
    cp.add_argument("--reason", help="Why these files are one pack.")
    for name in ("add-to-pack", "remove-from-pack"):
        verbs[name].add_argument("entry_id", type=int, help="The pack's entry id.")
        verbs[name].add_argument("path", help="A file or folder, relative to its root.")
        verbs[name].add_argument("--root-id", type=int)
    for name in ("report-product", "report-line"):
        verbs[name].add_argument("--id", type=int)
        verbs[name].add_argument("--type", dest="product_type")
        verbs[name].add_argument("--line", dest="product_line")
    verbs["report-product"].add_argument("--product")
    lu = verbs["list-unfiled"]
    lu.add_argument("--folder", help="A folder relative to its root.")
    lu.add_argument("--root-id", type=int)
    lu.add_argument("--recursive", action="store_true")
    lu.add_argument("--include-flagged", action="store_true")
    lu.add_argument("--limit", type=int, default=100)
    ll = verbs["list-lines"]
    ll.add_argument("--type", dest="product_type")
    ll.add_argument("--search")
    ll.add_argument("--limit", type=int, default=200)
    ro = verbs["reorganize"]
    ro.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would move, and change nothing.",
    )
    ro.add_argument(
        "--limit",
        type=int,
        help="Move at most this many files; skip the sweep of empty staging folders.",
    )
    cleanup = verbs["sanitize-filenames"]
    mode = cleanup.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Back up and apply cleanup.")
    mode.add_argument("--dry-run", action="store_true", help="Preview (the default).")
    cleanup.add_argument("--out", type=Path, help="Write the full JSON rename preview.")
    verbs["scan"].add_argument(
        "--root", type=Path, help="Scan only this registered root (default: all)."
    )
    fp = verbs["find-packs"]
    fp.add_argument(
        "--root", type=Path, help="Only this registered root (default: all)."
    )
    fp.add_argument("--limit", type=int, help="At most this many model calls.")
    fp.add_argument(
        "--dry-run",
        action="store_true",
        help="Ask and store answers, but form no packs.",
    )
    fp.add_argument("--no-search", action="store_true", help="Make no Google searches.")
    verbs["scan"].add_argument(
        "--force",
        action="store_true",
        help="Re-extract every file, ignoring the size+mtime skip rule.",
    )
    return parser


def main() -> None:
    load_env()
    args = build_parser().parse_args()
    catalog_path = resolve_catalog_path(args.catalog)
    handler = _HANDLERS.get(args.command, _not_implemented)
    if args.command == "serve":
        # The server configures its own logs, and one call event for its whole
        # lifetime would say nothing; its tool calls are logged individually.
        try:
            sys.exit(handler(args, catalog_path))
        except UsageError as error:
            print(f"error: {error}", file=sys.stderr)
            sys.exit(1)
    if catalog_path.exists():
        configure_wide_event_logs(catalog_path)
    try:
        arguments = {k: str(v) for k, v in vars(args).items() if k != "command"}
        with CallTracker(args.command, transport="cli", arguments=arguments):
            code = handler(args, catalog_path)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
