from pathlib import Path

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
    assert files_by_name["book.txt"]["media_type"] == "text"
    assert files_by_name["never_scanned.txt"]["cataloged"] is False
    assert files_by_name["never_scanned.txt"]["media_type"] is None
