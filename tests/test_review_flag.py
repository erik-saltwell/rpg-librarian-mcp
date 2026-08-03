from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from conftest import FakeProgressReporter, insert_raw_entry
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.FlagForReviewCommand import FlagForReviewCommand
from rpg_librarian_mcp.commands.ResolveReviewFlagCommand import (
    ResolveReviewFlagCommand,
)
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.review_items import (
    list_review_items as _list_review_items,
)
from rpg_librarian_mcp.model import Entry, ReviewFlag

JsonDict = dict[str, Any]


def list_review_items(*args: Any, **kwargs: Any) -> JsonDict:
    return cast(JsonDict, _list_review_items(*args, **kwargs))


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _entry(
    catalog: Catalog,
    filename: str,
    sha256: str = "a" * 64,
    write_real_file: bool = False,
) -> Entry:
    if write_real_file:
        file_path = catalog.library_root / "shelf" / "box" / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("x")
    insert_raw_entry(
        catalog,
        parent_path="shelf/box",
        filename=filename,
        media_type="pdf",
        mime_type="application/pdf",
        sha256=sha256,
    )
    with session_scope(catalog) as session:
        return session.exec(select(Entry).where(Entry.filename == filename)).one()


def test_open_flags_are_unique_per_entry_but_resolved_ones_are_not(tmp_path):
    catalog = _catalog(tmp_path)
    entry = _entry(catalog, "book.pdf")

    with session_scope(catalog) as session:
        session.add(ReviewFlag(entry_id=entry.id, reason="first"))
        session.commit()

    with session_scope(catalog) as session, pytest.raises(IntegrityError):
        session.add(ReviewFlag(entry_id=entry.id, reason="second"))
        session.commit()


def test_flag_for_review_rejects_empty_reason(tmp_path):
    """Bug: an empty (or whitespace-only) reason was silently accepted,
    producing an open review flag that gives a human reviewer no
    information about what needs attention."""
    catalog = _catalog(tmp_path)

    with pytest.raises(ValueError, match="reason must not be empty"):
        FlagForReviewCommand(catalog, reason="")


async def test_flag_for_review_creates_an_open_flag(tmp_path):
    catalog = _catalog(tmp_path)
    entry = _entry(catalog, "book.pdf")

    command = FlagForReviewCommand(catalog, reason="unsure which edition")
    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        flag = session.exec(
            select(ReviewFlag).where(ReviewFlag.entry_id == entry.id)
        ).one()
        assert flag.reason == "unsure which edition"
        assert flag.resolved_at is None


async def test_flag_for_review_updates_reason_instead_of_duplicating(tmp_path):
    catalog = _catalog(tmp_path)
    _entry(catalog, "book.pdf")

    await FlagForReviewCommand(catalog, reason="first guess").process(
        tmp_path, True, False, FakeProgressReporter()
    )
    await FlagForReviewCommand(catalog, reason="second guess").process(
        tmp_path, True, False, FakeProgressReporter()
    )

    with session_scope(catalog) as session:
        flags = session.exec(select(ReviewFlag)).all()
        assert len(flags) == 1
        assert flags[0].reason == "second guess"


async def test_flag_for_review_flags_every_entry_under_a_directory(tmp_path):
    catalog = _catalog(tmp_path)
    _entry(catalog, "book.pdf", sha256="a" * 64)
    _entry(catalog, "handout.pdf", sha256="b" * 64)

    command = FlagForReviewCommand(catalog, reason="whole product unclear")
    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.succeeded == 2
    with session_scope(catalog) as session:
        assert len(session.exec(select(ReviewFlag)).all()) == 2


async def test_resolve_review_flag_closes_an_open_flag(tmp_path):
    catalog = _catalog(tmp_path)
    entry = _entry(catalog, "book.pdf")
    await FlagForReviewCommand(catalog, reason="unsure").process(
        tmp_path, True, False, FakeProgressReporter()
    )

    result = await ResolveReviewFlagCommand(
        catalog, resolution_note="user confirmed it's the 2019 edition"
    ).process(tmp_path, True, False, FakeProgressReporter())

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        flag = session.exec(
            select(ReviewFlag).where(ReviewFlag.entry_id == entry.id)
        ).one()
        assert flag.resolved_at is not None
        assert flag.resolution_note == "user confirmed it's the 2019 edition"


async def test_resolve_review_flag_skips_entries_with_no_open_flag(tmp_path):
    catalog = _catalog(tmp_path)
    _entry(catalog, "book.pdf")

    result = await ResolveReviewFlagCommand(catalog, resolution_note="n/a").process(
        tmp_path, True, False, FakeProgressReporter()
    )

    assert result.skipped == 1
    assert result.succeeded == 0
    assert result.errored == 0


async def test_resolved_flags_can_be_reopened(tmp_path):
    """After a flag is resolved, flagging the same entry again must not
    collide with the partial-unique index on open flags."""
    catalog = _catalog(tmp_path)
    _entry(catalog, "book.pdf")
    await FlagForReviewCommand(catalog, reason="first pass").process(
        tmp_path, True, False, FakeProgressReporter()
    )
    await ResolveReviewFlagCommand(catalog, resolution_note="handled").process(
        tmp_path, True, False, FakeProgressReporter()
    )

    result = await FlagForReviewCommand(catalog, reason="second pass").process(
        tmp_path, True, False, FakeProgressReporter()
    )

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        flags = session.exec(select(ReviewFlag)).all()
        assert len(flags) == 2
        open_flags = [flag for flag in flags if flag.resolved_at is None]
        assert len(open_flags) == 1
        assert open_flags[0].reason == "second pass"


async def test_list_review_items_only_returns_open_flags(tmp_path):
    catalog = _catalog(tmp_path)
    _entry(catalog, "book.pdf", sha256="a" * 64, write_real_file=True)
    _entry(catalog, "handout.pdf", sha256="b" * 64, write_real_file=True)
    await FlagForReviewCommand(catalog, reason="open one").process(
        tmp_path / "shelf" / "box" / "book.pdf", False, False, FakeProgressReporter()
    )
    await FlagForReviewCommand(catalog, reason="will be resolved").process(
        tmp_path / "shelf" / "box" / "handout.pdf", False, False, FakeProgressReporter()
    )
    await ResolveReviewFlagCommand(catalog, resolution_note="done").process(
        tmp_path / "shelf" / "box" / "handout.pdf", False, False, FakeProgressReporter()
    )

    result = list_review_items(catalog)

    assert result["count"] == 1
    assert result["items"][0]["path"] == "shelf/box/book.pdf"
    assert result["items"][0]["reason"] == "open one"
