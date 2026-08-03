from pathlib import Path

import pytest
from sqlmodel import select

from conftest import FakeProgressReporter
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.commands.UpdateProductCommand import UpdateProductCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, IdentificationMethod, Product


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


async def _catalog_file(tmp_path: Path, parent: str, filename: str, text: str) -> Path:
    shelf = tmp_path / parent
    shelf.mkdir(parents=True, exist_ok=True)
    file_path = shelf / filename
    file_path.write_text(text)
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(
        tmp_path, True, False, FakeProgressReporter()
    )
    return file_path


def _get_entry(catalog: Catalog, filename: str) -> Entry:
    with session_scope(catalog) as session:
        return session.exec(select(Entry).where(Entry.filename == filename)).one()


async def test_creates_a_new_product_and_links_a_single_file(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    command = UpdateProductCommand(catalog)

    result, product_id, created = await command.run(
        file_path,
        False,
        "Call of Cthulhu",
        IdentificationMethod.manual,
        FakeProgressReporter(),
    )

    assert created is True
    assert result.succeeded == 1
    entry = _get_entry(catalog, "book.pdf")
    assert entry.product_id == product_id
    with session_scope(catalog) as session:
        product = session.get(Product, product_id)
        assert product is not None
        assert product.title == "Call of Cthulhu"
        assert product.identification_method == IdentificationMethod.manual


async def test_rejects_an_empty_title(tmp_path):
    """Bug: an empty-string title sailed through every check in the chain
    (all of which only tested `is not None`, never falsiness) and got
    persisted as a Product row with title=''."""
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    command = UpdateProductCommand(catalog)

    with pytest.raises(ValueError, match="title"):
        await command.run(
            file_path, False, "", IdentificationMethod.manual, FakeProgressReporter()
        )

    with session_scope(catalog) as session:
        assert session.exec(select(Product)).all() == []


async def test_reuses_an_existing_case_insensitive_match(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        existing = Product(
            title="Call of Cthulhu",
            system="CoC 7e",
            identification_method=IdentificationMethod.manual,
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
        existing_id = existing.id

    command = UpdateProductCommand(catalog)
    result, product_id, created = await command.run(
        file_path,
        False,
        "call of cthulhu",
        IdentificationMethod.isbn_match,
        FakeProgressReporter(),
        system="coc 7e",
    )

    assert created is False
    assert product_id == existing_id
    assert result.succeeded == 1
    with session_scope(catalog) as session:
        product = session.get(Product, existing_id)
        assert product is not None
        # Untouched: identification_method from the reusing call is not applied.
        assert product.identification_method == IdentificationMethod.manual


async def test_raises_when_multiple_products_match(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        session.add(
            Product(
                title="Call of Cthulhu",
                identification_method=IdentificationMethod.manual,
            )
        )
        session.add(
            Product(
                title="Call of Cthulhu",
                identification_method=IdentificationMethod.manual,
            )
        )
        session.commit()

    command = UpdateProductCommand(catalog)

    with pytest.raises(ValueError, match="2 existing products"):
        await command.run(
            file_path,
            False,
            "Call of Cthulhu",
            IdentificationMethod.manual,
            FakeProgressReporter(),
        )


async def test_raises_when_path_has_no_cataloged_entries(tmp_path):
    empty_dir = tmp_path / "shelf" / "empty"
    empty_dir.mkdir(parents=True)
    catalog = _catalog(tmp_path)
    command = UpdateProductCommand(catalog)

    with pytest.raises(ValueError, match="no cataloged entries"):
        await command.run(
            empty_dir,
            False,
            "Call of Cthulhu",
            IdentificationMethod.manual,
            FakeProgressReporter(),
        )


async def test_overwrites_an_entrys_existing_different_product(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        other_product = Product(
            title="Other Product", identification_method=IdentificationMethod.manual
        )
        session.add(other_product)
        session.commit()
        session.refresh(other_product)
        other_product_id = other_product.id
        entry = session.exec(select(Entry).where(Entry.filename == "book.pdf")).one()
        entry.product_id = other_product_id
        session.add(entry)
        session.commit()

    command = UpdateProductCommand(catalog)
    result, product_id, created = await command.run(
        file_path,
        False,
        "Call of Cthulhu",
        IdentificationMethod.manual,
        FakeProgressReporter(),
    )

    assert created is True
    assert result.succeeded == 1
    entry = _get_entry(catalog, "book.pdf")
    assert entry.product_id == product_id
    assert entry.product_id != other_product_id


async def test_recursive_links_every_entry_under_a_directory(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "one.pdf", "a")
    await _catalog_file(tmp_path, "shelf/box/sub", "two.pdf", "b")
    catalog = _catalog(tmp_path)
    command = UpdateProductCommand(catalog)

    result, product_id, _created = await command.run(
        tmp_path / "shelf" / "box",
        True,
        "Call of Cthulhu",
        IdentificationMethod.manual,
        FakeProgressReporter(),
    )

    assert result.succeeded == 2
    assert _get_entry(catalog, "one.pdf").product_id == product_id
    assert _get_entry(catalog, "two.pdf").product_id == product_id


async def test_second_call_skips_entries_already_linked_to_the_same_product(tmp_path):
    file_path = await _catalog_file(tmp_path, "shelf/box", "book.pdf", "hello")
    catalog = _catalog(tmp_path)
    command = UpdateProductCommand(catalog)
    await command.run(
        file_path,
        False,
        "Call of Cthulhu",
        IdentificationMethod.manual,
        FakeProgressReporter(),
    )

    second_command = UpdateProductCommand(catalog)
    result, _product_id, created = await second_command.run(
        file_path,
        False,
        "Call of Cthulhu",
        IdentificationMethod.manual,
        FakeProgressReporter(),
    )

    assert created is False
    assert result.skipped == 1
    assert result.succeeded == 0
