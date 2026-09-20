from __future__ import annotations

import argparse
from pathlib import Path

from sqlmodel import select

from ..db import session_scope
from ..errors import UsageError
from ..model import Root, RootKind


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Register a staging root (a dump folder). Does not scan it.

    Refuses a path nested inside, or containing, an existing root, so that no file
    can belong to two roots. Registering an already-registered path is a no-op.
    """
    path: Path = args.path.expanduser().resolve()
    if not path.is_dir():
        raise UsageError(f"{path} is not an existing directory.")

    with session_scope(catalog_path) as session:
        roots = session.exec(select(Root)).all()
        if not any(root.kind == RootKind.library for root in roots):
            raise UsageError("The catalog has no library root. Run `init` first.")
        for root in roots:
            existing = Path(root.path)
            if path == existing:
                print(f"Already registered: {path} ({root.kind})")
                return 0
            if path.is_relative_to(existing):
                raise UsageError(f"{path} is inside the existing root {existing}.")
            if existing.is_relative_to(path):
                raise UsageError(f"{path} contains the existing root {existing}.")
        session.add(Root(kind=RootKind.staging, path=str(path), label=args.label))

    print(f"Registered staging root: {path}")
    return 0
