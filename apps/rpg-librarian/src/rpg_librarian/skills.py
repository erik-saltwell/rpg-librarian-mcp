"""Install the bundled agent skills into an initialized library project."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

# All three agents discover project-local skills below their own hidden directory.
_SKILL_ROOTS = (".claude", ".codex", ".gemini")


def install_bundled_skills(project_root: Path) -> list[Path]:
    """Seed every bundled skill for Claude, Codex, and Gemini if it is missing.

    Existing files are deliberately left unchanged: `init` may be re-run safely and
    people can customize the local copies without a package upgrade erasing them.
    Returns the files newly installed during this call.
    """
    bundled = resources.files("rpg_librarian") / "resources" / "skills"
    installed: list[Path] = []
    with resources.as_file(bundled) as bundled_path:
        for skill in sorted(bundled_path.iterdir()):
            if not skill.is_dir() or not (skill / "SKILL.md").is_file():
                continue
            for agent_root in _SKILL_ROOTS:
                target = project_root / agent_root / "skills" / skill.name / "SKILL.md"
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(skill / "SKILL.md", target)
                installed.append(target)
    return installed
