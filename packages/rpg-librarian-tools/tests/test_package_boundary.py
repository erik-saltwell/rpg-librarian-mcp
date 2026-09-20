from pathlib import Path


def test_tools_package_does_not_import_mcp_application() -> None:
    source_root = Path(__file__).parents[1] / "src" / "rpg_librarian_tools"

    offenders = [
        path.relative_to(source_root)
        for path in source_root.rglob("*.py")
        if "rpg_librarian_mcp" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
