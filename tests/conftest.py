import pytest


@pytest.fixture(autouse=True)
def _isolate_from_ambient_database_url(monkeypatch):
    """Tests must not be affected by a dev-only DATABASE_URL in the repo's .env.

    An empty (but present) value stops env.py's `if database_url:` check from
    firing, and blocks python-dotenv's override=False load from re-populating
    it from any .env found while walking up from a tmp_path under the repo.
    """
    monkeypatch.setenv("DATABASE_URL", "")
