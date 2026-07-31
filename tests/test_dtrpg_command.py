from unittest.mock import MagicMock

from rpg_librarian_mcp.commands.SearchDtrpgCommand import SearchDtrpgCommand
from rpg_librarian_mcp.dtrpg.client import ProductDetails


def _product(product_id=1, authors=None, game_system=None):
    return ProductDetails(
        product_id=product_id,
        order_product_id=None,
        title="Shadowrun Sixth World Core Rulebook",
        description="A game of cyberpunk fantasy.",
        publisher="Catalyst Game Labs",
        authors=authors or [],
        game_system=game_system,
    )


def test_search_dtrpg_defaults_to_catalog_scope():
    client = MagicMock()
    client.search_products.return_value = [_product()]

    result = SearchDtrpgCommand(client).run("Shadowrun")

    client.search_products.assert_called_once_with("Shadowrun", 10)
    client.search_library.assert_not_called()
    assert result[0].source == "dtrpg"
    assert result[0].source_id == "1"
    assert result[0].title == "Shadowrun Sixth World Core Rulebook"
    assert result[0].publisher == "Catalyst Game Labs"


def test_search_dtrpg_library_scope_calls_search_library():
    client = MagicMock()
    client.search_library.return_value = []

    SearchDtrpgCommand(client).run("Shadowrun", scope="library", max_values=25)

    client.search_library.assert_called_once_with("Shadowrun", 25)
    client.search_products.assert_not_called()


def test_search_dtrpg_maps_creators_and_system():
    client = MagicMock()
    client.search_products.return_value = [
        _product(authors=["Jason M. Hardy"], game_system="Shadowrun")
    ]

    result = SearchDtrpgCommand(client).run("Shadowrun")

    assert result[0].creators == ["Jason M. Hardy"]
    assert result[0].system == "Shadowrun"


def test_search_dtrpg_empty_description_becomes_none():
    client = MagicMock()
    product = _product()
    product.description = ""
    client.search_products.return_value = [product]

    result = SearchDtrpgCommand(client).run("Shadowrun")

    assert result[0].description is None
