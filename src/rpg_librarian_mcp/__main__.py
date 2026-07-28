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
        help="Upgrade the current directory's catalog database to the latest "
        "schema and exit, instead of starting the server.",
    )
    args = parser.parse_args()

    if args.migrate:
        try:
            migrate_existing(Catalog.from_cwd())
        except RuntimeError as e:
            raise SystemExit(str(e)) from e
        return

    run()


if __name__ == "__main__":
    main()
