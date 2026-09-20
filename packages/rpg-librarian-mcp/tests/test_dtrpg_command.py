from unittest.mock import AsyncMock

import pytest

from rpg_librarian_mcp.commands.SearchDtrpgCommand import SearchDtrpgCommand
from rpg_librarian_tools.dtrpg import Product


def _product(authors: tuple[str, ...] = (), game_system: str | None = None) -> Product:
    return Product(
        1,
        None,
        "Shadowrun Sixth World Core Rulebook",
        "description",
        "Catalyst Game Labs",
        authors,
        game_system,
    )


async def test_search_dtrpg_defaults_to_catalog_scope():
    product_search = AsyncMock(return_value=(_product(),))
    library_search = AsyncMock()
    command = SearchDtrpgCommand("key", product_search, library_search)
    result = await command.run("Shadowrun")
    product_search.assert_awaited_once_with("Shadowrun", "key", 10)
    library_search.assert_not_awaited()
    assert result[0].source == "dtrpg"
    assert result[0].source_id == "1"
    assert result[0].title == "Shadowrun Sixth World Core Rulebook"
    assert result[0].publisher == "Catalyst Game Labs"


async def test_search_dtrpg_library_scope_calls_search_library():
    product_search = AsyncMock()
    library_search = AsyncMock(return_value=())
    command = SearchDtrpgCommand("key", product_search, library_search)
    await command.run("Shadowrun", scope="library", max_values=25)
    library_search.assert_awaited_once_with("Shadowrun", "key", 25)
    product_search.assert_not_awaited()


async def test_search_dtrpg_maps_creators_and_system():
    product_search = AsyncMock(
        return_value=(_product(("Jason M. Hardy",), "Shadowrun"),)
    )
    result = await SearchDtrpgCommand("key", product_search).run("Shadowrun")
    assert result[0].creators == ["Jason M. Hardy"]
    assert result[0].system == "Shadowrun"


async def test_search_dtrpg_empty_description_becomes_none():
    product_search = AsyncMock(
        return_value=(Product(1, None, "title", "", "publisher"),)
    )
    result = await SearchDtrpgCommand("key", product_search).run("Shadowrun")
    assert result[0].description is None


@pytest.mark.parametrize("limit", [-5, 0])
async def test_search_dtrpg_rejects_nonpositive_max_values_without_calling_tool(
    limit: int,
):
    product_search = AsyncMock()
    library_search = AsyncMock()
    command = SearchDtrpgCommand("key", product_search, library_search)
    with pytest.raises(ValueError, match="max_values"):
        await command.run("Shadowrun", max_values=limit)
    product_search.assert_not_awaited()
    library_search.assert_not_awaited()
