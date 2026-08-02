import contextlib
from pathlib import Path

from structlog.testing import capture_logs

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry
from rpg_librarian_mcp.server import create_server


async def test_all_tools_are_registered():
    mcp = create_server()
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "librarian_status",
        "update_catalog",
        "list_directory_entries",
        "summarize_directories",
        "list_errors",
        "run_readonly_query",
        "get_catalog_schema",
        "move",
        "update_metadata",
        "read_pdfs",
        "search_rpg_geek",
        "lookup_rpg_geek_product",
        "search_dtrpg",
        "lookup_isbn",
        "update_product",
        "ingest_external_source",
        "classify_content_role",
        "find_duplicates",
        "remove",
        "flag_for_review",
        "resolve_review_flag",
        "list_review_items",
        "get_entry_details",
    }


def test_library_root_is_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Catalog.from_cwd()
    assert config.library_root == tmp_path.resolve()
    assert config.catalog_dir == tmp_path.resolve() / ".catalog"


async def test_list_directory_entries_round_trips_through_the_registered_tool(
    tmp_path, monkeypatch
):
    """Exercises the actual @mcp.tool wrapper, not just the plain function.

    Covers FastMCP's Path-param coercion and output-schema validation for a
    dict[str, object] return -- list_directory_entries is a good pick since
    its payload carries both a MediaType enum value (for the cataloged file)
    and a None (for the uncataloged one).
    """
    monkeypatch.chdir(tmp_path)
    box = tmp_path / "shelf" / "box"
    box.mkdir(parents=True)
    (box / "book.txt").write_text("hello")
    (box / "never_scanned.txt").write_text("world")
    catalog = Catalog(library_root=tmp_path)
    with session_scope(catalog) as session:
        session.add(
            Entry(
                parent_path=Path("shelf/box"),
                filename="book.txt",
                sha256="a" * 64,
                size_in_bytes=5,
                mime_type="text/plain",
                media_type="text",
            )
        )
        session.commit()

    mcp = create_server()
    result = await mcp.call_tool("list_directory_entries", {"path": str(box)})

    assert result.structured_content is not None
    files_by_name = {f["filename"]: f for f in result.structured_content["files"]}
    assert files_by_name["book.txt"]["cataloged"] is True


async def test_tool_call_emits_one_wide_event_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp = create_server()

    with capture_logs() as logs:
        await mcp.call_tool("librarian_status", {})

    tool_call_logs = [entry for entry in logs if entry["event"] == "tool_call"]
    assert len(tool_call_logs) == 1
    entry = tool_call_logs[0]
    assert entry["tool"] == "librarian_status"
    assert entry["outcome"] == "success"
    assert isinstance(entry["duration_ms"], float)


async def test_tool_call_emits_one_wide_event_on_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp = create_server()

    with capture_logs() as logs, contextlib.suppress(Exception):
        await mcp.call_tool(
            "move",
            {
                "source": str(tmp_path / "nope"),
                "destination": str(tmp_path / "elsewhere"),
            },
        )

    tool_call_logs = [entry for entry in logs if entry["event"] == "tool_call"]
    assert len(tool_call_logs) == 1
    entry = tool_call_logs[0]
    assert entry["tool"] == "move"
    assert entry["outcome"] == "error"
    assert "error_type" in entry or "error_message" in entry
    assert isinstance(entry["duration_ms"], float)


async def test_tool_call_wide_event_carries_tool_specific_fields(tmp_path, monkeypatch):
    """`move` reports business-context fields (kind, entries_updated) via
    `log_event_fields`, and they should land in the same wide event -- not a
    second log line."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "book.txt"
    source.write_text("hello")
    destination = tmp_path / "shelf" / "box" / "book.txt"

    mcp = create_server()
    with capture_logs() as logs:
        await mcp.call_tool(
            "move", {"source": str(source), "destination": str(destination)}
        )

    tool_call_logs = [entry for entry in logs if entry["event"] == "tool_call"]
    assert len(tool_call_logs) == 1
    entry = tool_call_logs[0]
    assert entry["kind"] == "file"
    assert entry["entries_updated"] == 0


async def test_tool_call_wide_event_carries_fields_from_an_async_tool(
    tmp_path, monkeypatch
):
    """`update_catalog` is an async tool (no threadpool hop), covering the
    other dispatch path `log_event_fields` needs to work from."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "shelf" / "box").mkdir(parents=True)
    (tmp_path / "shelf" / "box" / "book.txt").write_text("hello")

    mcp = create_server()
    with capture_logs() as logs:
        await mcp.call_tool(
            "update_catalog",
            {"path": str(tmp_path), "process_recursively": True},
        )

    tool_call_logs = [entry for entry in logs if entry["event"] == "tool_call"]
    assert len(tool_call_logs) == 1
    entry = tool_call_logs[0]
    assert entry["scanned"] == 1
    assert entry["successfully_processed"] == 1
