from __future__ import annotations

import argparse

from .catalog import Catalog
from .db import migrate_existing
from .server import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="rpg-librarian-mcp")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Bring the current directory fully up to date -- create the "
        "catalog/CLAUDE.md/db if missing, upgrade the db schema to the "
        "latest version, and sync CLAUDE.md and bundled skills to the "
        "currently installed version -- then exit instead of starting the "
        "server.",
    )
    args = parser.parse_args()

    if args.migrate:
        migrate_existing(Catalog.from_cwd())
        return

    run()


if __name__ == "__main__":
    main()
