from unittest.mock import AsyncMock

from rpg_librarian_mcp.commands.LookupRpgGeekProductCommand import (
    LookupRpgGeekProductCommand,
)
from rpg_librarian_mcp.commands.SearchRpgGeekCommand import SearchRpgGeekCommand
from rpg_librarian_mcp.rpggeek.client import Candidate, ProductDetails


async def test_search_rpg_geek_maps_candidates_to_product_candidate():
    client = AsyncMock()
    client.find_candidates.return_value = [
        Candidate(rpggeek_id=123, name="Call of Cthulhu 7E", year_published=2014),
        Candidate(rpggeek_id=456, name="Call of Cthulhu Keeper Rulebook"),
    ]

    result = await SearchRpgGeekCommand(client).run(name="Call of Cthulhu", isbn=None)

    client.find_candidates.assert_awaited_once_with("Call of Cthulhu", None, 5)
    assert result[0].source == "rpggeek"
    assert result[0].source_id == "123"
    assert result[0].title == "Call of Cthulhu 7E"
    assert result[0].year_published == 2014
    assert result[1].year_published is None


async def test_search_rpg_geek_passes_through_max_values():
    client = AsyncMock()
    client.find_candidates.return_value = []

    await SearchRpgGeekCommand(client).run(name="x", isbn=None, max_values=3)

    client.find_candidates.assert_awaited_once_with("x", None, 3)


async def test_lookup_rpg_geek_product_maps_full_details():
    client = AsyncMock()
    client.get_product_details.return_value = ProductDetails(
        rpggeek_id=123,
        name="Call of Cthulhu 7E",
        year_published=2014,
        description="A game of horror.",
        systems=["Call of Cthulhu"],
        categories=["Horror"],
        designers=["Sandy Petersen", "Mike Mason"],
        publishers=["Chaosium"],
        thumbnail_url="https://example.com/thumb.jpg",
        rating=8.1,
    )

    result = await LookupRpgGeekProductCommand(client).run(123)

    client.get_product_details.assert_awaited_once_with(123)
    assert result.source == "rpggeek"
    assert result.source_id == "123"
    assert result.title == "Call of Cthulhu 7E"
    assert result.publisher == "Chaosium"
    assert result.system == "Call of Cthulhu"
    assert result.creators == ["Sandy Petersen", "Mike Mason"]
    assert result.categories == ["Horror"]
    assert result.rating == 8.1


async def test_lookup_rpg_geek_product_handles_missing_publisher_and_system():
    client = AsyncMock()
    client.get_product_details.return_value = ProductDetails(
        rpggeek_id=1, name="Unlisted Game"
    )

    result = await LookupRpgGeekProductCommand(client).run(1)

    assert result.publisher is None
    assert result.system is None
    assert result.creators == []
