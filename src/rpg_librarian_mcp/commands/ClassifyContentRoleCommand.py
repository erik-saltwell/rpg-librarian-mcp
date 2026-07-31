from __future__ import annotations

import uuid
from pathlib import Path
from typing import ClassVar

import litellm
from fastmcp import Context
from sqlmodel import Session, select

from ..catalog import Catalog
from ..db import session_scope
from ..llm.content_role_judgment import judge_content_role
from ..model import Entry, Error, PdfContents, ProcessingStage, Product
from .UpdateBaseCommand import UpdateBaseCommand, UpdateResult


class ClassifyContentRoleCommand(UpdateBaseCommand):
    """Classify each entry's product into a content role via an LLM judgment.

    `content_role` lives on `Product`, not `Entry` -- a product can span
    several entries (e.g. a rulebook plus its own map images), so this
    classifies once per product: whichever entry is processed first for a
    given product triggers the LLM call, and every other entry sharing that
    product is then a cheap `should_process` skip.
    """

    fatal_exceptions: ClassVar[tuple[type[BaseException], ...]] = (
        litellm.AuthenticationError,
        litellm.RateLimitError,
    )

    def __init__(self, catalog: Catalog, max_errors: int = 50) -> None:
        super().__init__(catalog, ProcessingStage.classify_content_role, max_errors)
        self._agnostic_product_ids: set[uuid.UUID] = set()

    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        ctx: Context,
    ) -> UpdateResult:
        """Same as the base `process`, plus a one-time resolution of which
        products are agnostic.

        `in_scope` (unlike `should_process`) gets no `session` and, per
        `UpdateBaseCommand`'s own contract, is a hard type filter that
        applies even when `force=True` -- system-agnostic content has no
        role tier to classify, full stop, not a staleness condition a
        caller should be able to force past. Resolving the set once here
        (rather than querying per-entry) mirrors `UpdateProductCommand`'s
        "resolve once up front, per-entry hooks stay cheap" shape.
        """
        with session_scope(self.catalog) as session:
            self._agnostic_product_ids = {
                product.id
                for product in session.exec(
                    select(Product).where(Product.system == Product.AGNOSTIC)
                ).all()
            }
        return await super().process(starting_path, process_recursively, force, ctx)

    def in_scope(self, entry: Entry) -> bool:
        """Entries with no product, or an agnostic one, are never classified."""
        return entry.has_product and entry.product_id not in self._agnostic_product_ids

    def should_process(self, session: Session, entry: Entry) -> bool:
        product = session.get(Product, entry.product_id)
        if product is None or product.system == Product.AGNOSTIC:
            return False

        existing_error = session.get(Error, (entry.id, self.processing_stage))
        if product.content_role is not None and existing_error is None:
            return False

        return self._gather_context(session, product) is not None

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        product = session.get(Product, entry.product_id)
        assert product is not None  # in_scope guarantees a product exists

        context_text = self._gather_context(session, product)
        if context_text is None:
            raise ValueError(
                f"product {product.id} has no description or sample text to "
                "classify from -- run lookup_isbn/lookup_rpg_geek_product/"
                "read_pdfs first"
            )

        judgment = judge_content_role(context_text)
        product.content_role = judgment.content_role
        session.add(product)

    def _gather_context(self, session: Session, product: Product) -> str | None:
        """Product description plus sample text/description from every
        linked PDF entry, or `None` if there's nothing to classify from."""
        parts: list[str] = []
        if product.description:
            parts.append(product.description)

        sibling_entries = session.exec(
            select(Entry).where(Entry.product_id == product.id)
        ).all()
        for sibling in sibling_entries:
            pdf_contents = session.get(PdfContents, sibling.id)
            if pdf_contents is None:
                continue
            if pdf_contents.description:
                parts.append(pdf_contents.description)
            if pdf_contents.sample_text:
                parts.append(pdf_contents.sample_text)

        combined = "\n".join(parts).strip()
        return combined or None
