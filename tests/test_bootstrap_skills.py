from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import ensure_bootstrapped


def _catalog(tmp_path):
    return Catalog(library_root=tmp_path)


def test_first_bootstrap_deploys_every_packaged_skill(tmp_path):
    catalog = _catalog(tmp_path)

    ensure_bootstrapped(catalog)

    assert (
        tmp_path / ".claude" / "skills" / "rpg-librarian-mcp-test" / "SKILL.md"
    ).exists()


def test_bootstrap_never_overwrites_an_existing_skill(tmp_path):
    skill_dir = tmp_path / ".claude" / "skills" / "rpg-librarian-mcp-test"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("my own edits, do not touch")
    catalog = _catalog(tmp_path)

    ensure_bootstrapped(catalog)

    assert (skill_dir / "SKILL.md").read_text() == "my own edits, do not touch"


def test_bootstrap_does_not_redeploy_skills_once_catalog_dir_already_exists(
    tmp_path,
):
    """Skills are only seeded at the moment .catalog is first created -- once
    the catalog dir exists, a later-deleted skill is not replaced."""
    catalog = _catalog(tmp_path)
    ensure_bootstrapped(catalog)
    skill_dir = tmp_path / ".claude" / "skills" / "rpg-librarian-mcp-test"
    (skill_dir / "SKILL.md").unlink()

    ensure_bootstrapped(catalog)

    assert not (skill_dir / "SKILL.md").exists()
