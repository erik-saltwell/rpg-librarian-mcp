from importlib import resources
from pathlib import Path

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import ensure_bootstrapped


def _catalog(tmp_path):
    return Catalog(library_root=tmp_path)


def _packaged_claude_md_text() -> str:
    resource = resources.files("rpg_librarian_mcp") / "resources" / "CLAUDE.md"
    return resource.read_text(encoding="utf-8")


def test_first_bootstrap_creates_claude_md_from_the_packaged_resource(tmp_path):
    catalog = _catalog(tmp_path)

    ensure_bootstrapped(catalog)

    claude_md_path = tmp_path / "CLAUDE.md"
    assert claude_md_path.exists()
    assert claude_md_path.read_text(encoding="utf-8") == _packaged_claude_md_text()


def test_bootstrap_never_overwrites_an_existing_claude_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("my own notes, do not touch")
    catalog = _catalog(tmp_path)

    ensure_bootstrapped(catalog)

    assert (tmp_path / "CLAUDE.md").read_text() == "my own notes, do not touch"


def test_bootstrap_does_not_recreate_claude_md_once_catalog_dir_already_exists(
    tmp_path,
):
    """CLAUDE.md is only seeded at the moment .catalog is first created --
    once the catalog dir exists, a later-deleted CLAUDE.md is not replaced."""
    catalog = _catalog(tmp_path)
    ensure_bootstrapped(catalog)
    (tmp_path / "CLAUDE.md").unlink()

    ensure_bootstrapped(catalog)

    assert not (tmp_path / "CLAUDE.md").exists()


def test_bootstrap_writes_claude_md_with_explicit_utf8_encoding(tmp_path, monkeypatch):
    """The packaged CLAUDE.md contains non-ASCII characters (em dashes,
    typographic apostrophes). Writing without an explicit encoding would use
    the platform default, which raises UnicodeEncodeError under a non-UTF-8
    locale (e.g. a stripped subprocess environment) -- so the write must
    always pin encoding="utf-8" rather than relying on the ambient default.
    """
    seen_encodings = []
    original_write_text = Path.write_text

    def _spy(self, data, *args, **kwargs):
        if self.name == "CLAUDE.md":
            seen_encodings.append(kwargs.get("encoding"))
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _spy)
    catalog = _catalog(tmp_path)

    ensure_bootstrapped(catalog)

    assert seen_encodings == ["utf-8"]
