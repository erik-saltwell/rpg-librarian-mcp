from __future__ import annotations

from .catalog import Catalog
from .cli import build_parser, dispatch
from .db import migrate_existing
from .server import run


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.migrate:
        migrate_existing(Catalog.from_cwd())
        return

    if args.command is not None:
        dispatch(args)
        return

    run()


if __name__ == "__main__":
    main()
