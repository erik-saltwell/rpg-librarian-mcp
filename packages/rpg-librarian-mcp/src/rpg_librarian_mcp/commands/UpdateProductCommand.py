from __future__ import annotations

import uuid
from pathlib import Path

from sqlmodel import Session, func, select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry, IdentificationMethod, ProcessingStage, Product
from ..progress import ProgressReporter
from .UpdateBaseCommand import UpdateBaseCommand, UpdateResult


class UpdateProductCommand(UpdateBaseCommand):
    """Find-or-create a Product from caller-supplied details, then link
    every entry under a path to it.

    Two distinct steps, not one: `run` resolves (or creates) the target
    Product exactly once, in its own transaction, before any entry is
    touched -- `UpdateBaseCommand`'s `should_process`/`process_one` are
    per-entry by design and have no hook for "do this once up front."
    Only the second step (stamping `product_id` onto each entry) goes
    through `UpdateBaseCommand.process`.
    """

    def __init__(self, catalog: Catalog, max_errors: int = 50) -> None:
        super().__init__(catalog, ProcessingStage.link_product, max_errors)
        self._resolved_product_id: uuid.UUID | None = None

    def should_process(self, session: Session, entry: Entry) -> bool:
        return entry.product_id != self._resolved_product_id

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        entry.product_id = self._resolved_product_id
        session.add(entry)

    async def run(
        self,
        path: Path,
        process_recursively: bool,
        title: str,
        identification_method: IdentificationMethod,
        reporter: ProgressReporter,
        description: str | None = None,
        artists: str | None = None,
        publisher: str | None = None,
        year: str | None = None,
        system: str | None = None,
    ) -> tuple[UpdateResult, uuid.UUID, bool]:
        if not title.strip():
            raise ValueError("title must not be empty")

        with session_scope(self.catalog) as session:
            entries = self._resolve_entries(session, path, process_recursively)
            if not entries:
                raise ValueError(f"no cataloged entries found under {path}")

            product, created = self._find_or_create_product(
                session,
                title,
                identification_method,
                description,
                artists,
                publisher,
                year,
                system,
            )
            self._resolved_product_id = product.id

        result = await self.process(path, process_recursively, False, reporter)
        return result, self._resolved_product_id, created

    def _find_or_create_product(
        self,
        session: Session,
        title: str,
        identification_method: IdentificationMethod,
        description: str | None,
        artists: str | None,
        publisher: str | None,
        year: str | None,
        system: str | None,
    ) -> tuple[Product, bool]:
        filters = []
        for column, value in (
            (Product.title, title),
            (Product.description, description),
            (Product.artists, artists),
            (Product.publisher, publisher),
            (Product.system, system),
        ):
            if value is not None:
                filters.append(func.lower(column) == value.lower())
        if year is not None:
            filters.append(Product.year == year)

        matches = list(session.exec(select(Product).where(*filters)).all())

        if len(matches) > 1:
            raise ValueError(
                f"{len(matches)} existing products match the given details -- "
                "pass more distinguishing fields (e.g. system) to disambiguate"
            )
        if matches:
            return matches[0], False

        product = Product(
            title=title,
            description=description,
            artists=artists,
            publisher=publisher,
            year=year,
            identification_method=identification_method,
            **({"system": system} if system is not None else {}),
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return product, True
