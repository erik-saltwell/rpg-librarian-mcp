from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_env, resolve_catalog_path

_VERBS = {
    "init": "Create the catalog and register the library root.",
    "add-source": "Register a staging root (a dump folder).",
    "scan": "Walk roots and record files, hashes, and metadata.",
    "enrich": "Look up external evidence and extract with an LLM.",
    "reorganize": "Make the share match the catalog.",
    "serve": "Run the MCP server on stdio.",
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
    for name, help_text in _VERBS.items():
        subparsers.add_parser(name, help=help_text, parents=[common])
    return parser


def main() -> None:
    load_env()
    args = build_parser().parse_args()
    catalog = resolve_catalog_path(args.catalog)
    print(f"{args.command}: not implemented yet (catalog: {catalog})", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
