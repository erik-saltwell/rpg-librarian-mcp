from pathlib import Path

from rpg_librarian_mcp.tools.path_helper import is_filtered


def test_filters_claude_md_uppercase():
    assert is_filtered(Path("/library/CLAUDE.md")) is True


def test_filters_claude_md_lowercase_for_pre_existing_files():
    """A library bootstrapped before the CLAUDE.md casing fix may still have
    a lowercase claude.md on disk -- it must still be excluded from
    cataloging, not suddenly treated as library content."""
    assert is_filtered(Path("/library/claude.md")) is True


def test_filters_agents_md_uppercase():
    assert is_filtered(Path("/library/AGENTS.md")) is True


def test_does_not_filter_ordinary_files():
    assert is_filtered(Path("/library/Keeper Rulebook.pdf")) is False


def test_filters_dotfiles_by_prefix():
    assert is_filtered(Path("/library/.hidden")) is True
