from rpg_librarian_mcp.config import Config
from rpg_librarian_mcp.server import create_server


async def test_status_tool_is_registered():
    mcp = create_server()
    tools = await mcp.list_tools()
    assert "librarian_status" in {tool.name for tool in tools}


def test_library_root_is_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Config.from_cwd()
    assert config.library_root == tmp_path.resolve()
    assert config.catalog_dir == tmp_path.resolve() / ".catalog"
