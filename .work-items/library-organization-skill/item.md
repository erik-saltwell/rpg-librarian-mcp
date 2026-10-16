---
name: "Library organization and cleanup skill"
status: complete
---

# Library organization and cleanup skill

Create a callable skill that asks an LLM to review catalog organization and improve the corresponding library organization. Apply clear-cut corrections automatically; save judgment calls for the existing review-items skill.

- [intent.md](intent.md) — agreed behavior, accepted workshop decisions, approved rubric, and open design questions.
- [idea.md](idea.md) — workshop outcome and rationale.
- [evaluations.md](evaluations.md) — qualitative assessment of the unbuilt concept.

Completed 2026-10-11: `review-organization` is implemented and installed in the library workspace, with database-backed coverage and decisions, atomic catalog corrections, and review-items integration. Restart the librarian MCP server to load the new tools, then invoke the skill. Physical moves remain the separate `reorganize` command. Verification and practical limits are recorded in progress.md.

- [plan.md](plan.md) — completed implementation and verification plan.
- [progress.md](progress.md) — delivered behavior, installation, verification, and limitations.
- [Skill](../../apps/rpg-librarian/src/rpg_librarian/resources/skills/review-organization/SKILL.md) — callable review-organization instructions.
