from __future__ import annotations

import argparse
from pathlib import Path

from sqlmodel import col, select

from ..db import session_scope, upgrade
from ..errors import UsageError
from ..model import ProductType, Root, RootKind
from ..product_types import SEED_PRODUCT_TYPES
from ..skills import install_bundled_skills


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Create the catalog, seed the product types, and register the library root.

    Idempotent: re-running with the same library adds nothing, and a catalog missing
    a seed type is repaired. A second, different library root is refused.
    """
    library: Path = args.library.expanduser().resolve()
    if not library.is_dir():
        raise UsageError(f"Library root {library} is not an existing directory.")

    created = not catalog_path.exists()
    upgrade(catalog_path)
    with session_scope(catalog_path) as session:
        existing = session.exec(
            select(Root).where(col(Root.kind) == RootKind.library)
        ).first()
        if existing is not None and Path(existing.path) != library:
            raise UsageError(
                f"The catalog already has library root {existing.path}; "
                f"refusing to register {library}."
            )
        if existing is None:
            session.add(Root(kind=RootKind.library, path=str(library)))

        known = set(session.exec(select(ProductType.name)).all())
        missing = [name for name in SEED_PRODUCT_TYPES if name not in known]
        session.add_all(ProductType(name=name) for name in missing)

    print(f"{'Created' if created else 'Using'} catalog {catalog_path}")
    print(f"Library root: {library}")
    if missing:
        print(f"Added {len(missing)} product type(s): {', '.join(missing)}")
    installed_skills = install_bundled_skills(library)
    if installed_skills:
        print(f"Installed {len(installed_skills)} bundled agent skill file(s).")
    return 0
