from pathlib import Path
from unittest.mock import AsyncMock

from sqlmodel import select

from conftest import insert_raw_entry
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands import ClassifyContentRoleCommand as command_module
from rpg_librarian_mcp.commands.ClassifyContentRoleCommand import (
    ClassifyContentRoleCommand,
)
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import (
    ContentRole,
    Entry,
    Error,
    IdentificationMethod,
    PdfContents,
    Product,
)


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _add_product(catalog: Catalog, **kwargs) -> Product:
    with session_scope(catalog) as session:
        product = Product(
            title="Keeper Rulebook",
            identification_method=IdentificationMethod.manual,
            **kwargs,
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return product


def _insert_pdf_entry(
    catalog: Catalog, filename: str, product_id, sha256: str = "a" * 64
) -> Entry:
    insert_raw_entry(
        catalog,
        parent_path="shelf/box",
        filename=filename,
        media_type="pdf",
        mime_type="application/pdf",
        sha256=sha256,
    )
    with session_scope(catalog) as session:
        entry = session.exec(select(Entry).where(Entry.filename == filename)).one()
        entry.product_id = product_id
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


class _Judgment:
    def __init__(self, content_role: ContentRole) -> None:
        self.content_role = content_role


def _stub_judgment(monkeypatch, role: ContentRole = ContentRole.core_rules) -> None:
    monkeypatch.setattr(
        command_module, "judge_content_role", lambda context_text: _Judgment(role)
    )


def test_in_scope_is_false_when_entry_has_no_product(tmp_path):
    catalog = _catalog(tmp_path)
    insert_raw_entry(
        catalog,
        parent_path="shelf/box",
        filename="book.pdf",
        media_type="pdf",
        mime_type="application/pdf",
    )
    with session_scope(catalog) as session:
        entry = session.exec(select(Entry).where(Entry.filename == "book.pdf")).one()

    command = ClassifyContentRoleCommand(catalog)
    assert command.in_scope(entry) is False


def test_should_process_is_false_for_agnostic_products(tmp_path):
    catalog = _catalog(tmp_path)
    product = _add_product(catalog, system=Product.AGNOSTIC, description="a map pack")
    entry = _insert_pdf_entry(catalog, "book.pdf", product.id)

    command = ClassifyContentRoleCommand(catalog)
    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is False


def test_should_process_is_false_with_no_description_or_sample_text(tmp_path):
    catalog = _catalog(tmp_path)
    product = _add_product(catalog, system="Call of Cthulhu")
    entry = _insert_pdf_entry(catalog, "book.pdf", product.id)

    command = ClassifyContentRoleCommand(catalog)
    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is False


def test_should_process_is_true_with_a_product_description(tmp_path):
    catalog = _catalog(tmp_path)
    product = _add_product(
        catalog, system="Call of Cthulhu", description="the core rulebook"
    )
    entry = _insert_pdf_entry(catalog, "book.pdf", product.id)

    command = ClassifyContentRoleCommand(catalog)
    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


def test_should_process_is_true_with_a_sibling_entrys_sample_text(tmp_path):
    catalog = _catalog(tmp_path)
    product = _add_product(catalog, system="Call of Cthulhu")
    entry = _insert_pdf_entry(catalog, "book.pdf", product.id)
    with session_scope(catalog) as session:
        session.add(PdfContents(entry_id=entry.id, sample_text='{"1": "keeper text"}'))
        session.commit()

    command = ClassifyContentRoleCommand(catalog)
    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


def test_should_process_is_false_once_content_role_is_set(tmp_path):
    catalog = _catalog(tmp_path)
    product = _add_product(
        catalog,
        system="Call of Cthulhu",
        description="the core rulebook",
        content_role=ContentRole.core_rules,
    )
    entry = _insert_pdf_entry(catalog, "book.pdf", product.id)

    command = ClassifyContentRoleCommand(catalog)
    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is False


def test_should_process_is_true_when_content_role_set_but_entry_has_a_stale_error(
    tmp_path,
):
    catalog = _catalog(tmp_path)
    product = _add_product(
        catalog,
        system="Call of Cthulhu",
        description="the core rulebook",
        content_role=ContentRole.core_rules,
    )
    entry = _insert_pdf_entry(catalog, "book.pdf", product.id)
    with session_scope(catalog) as session:
        session.add(
            Error(
                entry_id=entry.id,
                stage=command_module.ProcessingStage.classify_content_role,
                error_text="boom",
            )
        )
        session.commit()

    command = ClassifyContentRoleCommand(catalog)
    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


async def test_process_writes_content_role_from_description(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    product = _add_product(
        catalog, system="Call of Cthulhu", description="the core rulebook"
    )
    _insert_pdf_entry(catalog, "book.pdf", product.id)
    _stub_judgment(monkeypatch, ContentRole.core_rules)

    command = ClassifyContentRoleCommand(catalog)
    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.content_role == ContentRole.core_rules


async def test_process_classifies_once_per_product_not_per_entry(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    product = _add_product(
        catalog, system="Call of Cthulhu", description="the core rulebook"
    )
    _insert_pdf_entry(catalog, "book.pdf", product.id, sha256="a" * 64)
    _insert_pdf_entry(catalog, "handout.pdf", product.id, sha256="b" * 64)

    calls: list[str] = []

    def _fake_judge(context_text: str):
        calls.append(context_text)
        return _Judgment(ContentRole.core_rules)

    monkeypatch.setattr(command_module, "judge_content_role", _fake_judge)

    command = ClassifyContentRoleCommand(catalog)
    result = await command.process(tmp_path, True, False, AsyncMock())

    assert result.succeeded == 1
    assert result.skipped == 1
    assert len(calls) == 1


async def test_process_one_raises_with_no_context_when_forced(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    product = _add_product(catalog, system="Call of Cthulhu")
    _insert_pdf_entry(catalog, "book.pdf", product.id)
    _stub_judgment(monkeypatch)

    command = ClassifyContentRoleCommand(catalog)
    result = await command.process(tmp_path, True, True, AsyncMock())

    assert result.errored == 1


async def test_force_does_not_bypass_the_agnostic_skip(tmp_path, monkeypatch):
    """`force` reprocesses stale results -- it must not make agnostic
    products (which have no role tier at all) classifiable."""
    catalog = _catalog(tmp_path)
    product = _add_product(
        catalog, system=Product.AGNOSTIC, description="a generic map pack"
    )
    _insert_pdf_entry(catalog, "book.pdf", product.id)

    calls: list[str] = []
    monkeypatch.setattr(
        command_module,
        "judge_content_role",
        lambda context_text: (
            calls.append(context_text) or _Judgment(ContentRole.extras)
        ),
    )

    command = ClassifyContentRoleCommand(catalog)
    result = await command.process(tmp_path, True, True, AsyncMock())

    assert calls == []
    assert result.skipped == 1
    with session_scope(catalog) as session:
        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.content_role is None
    assert result.succeeded == 0
