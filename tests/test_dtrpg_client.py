import pytest

from rpg_librarian_mcp.dtrpg.client import DriveThruRPGClient


def test_missing_api_key_raises_a_clean_error(monkeypatch):
    """Bug: DriveThruRPGClient.__init__ did `os.environ["DTRPG_API_KEY"]`
    directly, so a missing key leaked a bare `KeyError: 'DTRPG_API_KEY'`
    instead of a clean, actionable error message."""
    monkeypatch.delenv("DTRPG_API_KEY", raising=False)

    with pytest.raises(ValueError, match="DTRPG_API_KEY"):
        DriveThruRPGClient()
