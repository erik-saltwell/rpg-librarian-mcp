from unittest.mock import AsyncMock

import pytest

from rpg_librarian_mcp.commands.LookupRpgGeekProductCommand import (
    LookupRpgGeekProductCommand,
)
from rpg_librarian_mcp.commands.SearchRpgGeekCommand import SearchRpgGeekCommand
from rpg_librarian_tools.rpggeek import Candidate, ProductDetails


async def test_search_rpg_geek_maps_candidates_to_product_candidate():
    operation = AsyncMock(
        return_value=[
            Candidate(rpggeek_id=123, name="Call of Cthulhu 7E", year_published=2014)
        ]
    )
    result = await SearchRpgGeekCommand(None, operation).run("Call of Cthulhu", None)
    operation.assert_awaited_once_with("Call of Cthulhu", 5, None)
    assert result[0].source == "rpggeek"
    assert result[0].source_id == "123"
    assert result[0].year_published == 2014


async def test_search_rpg_geek_tries_isbn_then_falls_back_to_name():
    operation = AsyncMock(
        side_effect=[[], [Candidate(rpggeek_id=123, name="Fallback result")]]
    )
    result = await SearchRpgGeekCommand("token", operation).run(
        "Fallback", "9780306406157"
    )
    assert [call.args for call in operation.await_args_list] == [
        ("9780306406157", 5, "token"),
        ("Fallback", 5, "token"),
    ]
    assert result[0].source_id == "123"


async def test_lookup_rpg_geek_product_maps_full_details():
    operation = AsyncMock(
        return_value=ProductDetails(
            rpggeek_id=123,
            name="Call of Cthulhu 7E",
            year_published=2014,
            description="A game of horror.",
            systems=["Call of Cthulhu"],
            categories=["Horror"],
            designers=["Sandy Petersen"],
            publishers=["Chaosium"],
            rating=8.1,
        )
    )
    result = await LookupRpgGeekProductCommand(None, operation).run(123)
    operation.assert_awaited_once_with(123, None)
    assert result.source == "rpggeek"
    assert result.publisher == "Chaosium"
    assert result.system == "Call of Cthulhu"
    assert result.creators == ["Sandy Petersen"]


@pytest.mark.parametrize("identifier", [-1, 0])
async def test_lookup_rpg_geek_product_rejects_nonpositive_ids(identifier: int):
    operation = AsyncMock()
    with pytest.raises(ValueError, match="rpggeek_id"):
        await LookupRpgGeekProductCommand(None, operation).run(identifier)
    operation.assert_not_awaited()


@pytest.mark.parametrize("limit", [-5, 0])
async def test_search_rpg_geek_rejects_nonpositive_max_values(limit: int):
    operation = AsyncMock()
    with pytest.raises(ValueError, match="max_values"):
        await SearchRpgGeekCommand(None, operation).run("x", None, limit)
    operation.assert_not_awaited()
