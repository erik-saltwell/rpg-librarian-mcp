from rpg_librarian_mcp import catalog as catalog_module
from rpg_librarian_mcp.catalog import load_env


def test_load_env_searches_from_the_package_not_the_cwd(monkeypatch, tmp_path):
    """Bug: load_env used find_dotenv(usecwd=True), which searches upward
    from the library root the server was launched in. In practice that
    directory rarely has a .env (credentials belong with the server
    installation), so tools silently ran with no env loaded. It must search
    from this module's location instead, regardless of the cwd."""
    calls = []

    def _fake_find_dotenv(*args, **kwargs):
        calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(catalog_module, "find_dotenv", _fake_find_dotenv)
    monkeypatch.chdir(tmp_path)

    load_env()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert "usecwd" not in kwargs or kwargs["usecwd"] is False
    assert not args
