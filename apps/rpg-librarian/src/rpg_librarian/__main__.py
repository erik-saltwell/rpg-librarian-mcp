from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from .commands import add_source, enrich, init, scan
from .config import load_env, resolve_catalog_path
from .enrichment.registry import SOURCES
from .errors import UsageError
from .observability import CallTracker, configure_wide_event_logs

Handler = Callable[[argparse.Namespace, Path], int]

_VERBS = {
    "init": "Create the catalog and register the library root.",
    "add-source": "Register a staging root (a dump folder).",
    "scan": "Walk roots and record files, hashes, and metadata.",
    "enrich": "Look up external evidence and extract with an LLM.",
    "reorganize": "Make the share match the catalog.",
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
    "enrich": enrich.run,
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
    verbs["scan"].add_argument(
        "--root", type=Path, help="Scan only this registered root (default: all)."
    )
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
    if catalog_path.exists():
        configure_wide_event_logs(catalog_path)
    try:
        with CallTracker(args.command, transport="cli") as tracker:
            tracker.fields["arguments"] = {
                k: str(v) for k, v in vars(args).items() if k != "command"
            }
            code = handler(args, catalog_path)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
