# Implementation handoff

Completed 2026-10-11. Approved skill name: **review-organization**.

## Delivered

- Bundled [review-organization skill](../../apps/rpg-librarian/src/rpg_librarian/resources/skills/review-organization/SKILL.md), using the invoking LLM and librarian MCP tools to inspect related groups, automatically correct clear-cut issues, and defer judgment calls.
- Additive Alembic migration **0007** and SQLModel entities for `organization_coverage`, `organization_run`, and `organization_finding`. Findings store stable file IDs, explanations, proposed operations, before/after context, and explicit owner resolutions, independently of entry foreign keys.
- Six MCP tools: start/resume a bounded pass; inspect paginated product/folder/line context and decision history; commit a group correction or recommendation; retrieve a receipt; list findings; and resolve the owner's chosen recommendation.
- Product and pack services execute ordered corrections in one transaction. Current source/destination fingerprints are checked under a writer reservation. A failed correction rolls back through a savepoint and becomes one review finding. Stale snapshots and unchanged owner decisions fail without marking coverage or generating another question.
- Corrections preserve kept/superseded dispositions. Removed filed members must be reassigned in the same correction. Generated-entry references support pack changes without guessed entry IDs. Open review questions survive assignments and entry replacement.
- Deferred findings append linked blocks to existing review flags, preserving unrelated text. Updated [review-items](../../apps/rpg-librarian/src/rpg_librarian/resources/skills/review-items/SKILL.md) presents each group proposal once and uses the resolution tool to retain the owner's decision. Reject/apply/alternative choices become durable history; materially changed evidence needs an explanation to reconsider them.
- Coverage fingerprints omit refresh timestamps. Queue discovery streams fingerprints; individual review calls load the selected groups and related context. The default batch has three products/unassigned folders, with optional line scope and a maximum batch of twenty groups. Interrupted runs resume; later passes pick unseen or changed groups.
- README instructions, schema notes, and server guidance updated.

## Installed copies

Installed `review-organization` and updated `review-items` under
`/home/eriksalt/data/rpg-librarian/{.claude,.codex,.gemini}/skills/`.
The prior Claude review-items copy matched the unmodified bundled version and was
backed up under `/home/eriksalt/data/rpg-librarian/backups/skills.pre-organization-review/.claude/review-items/` before replacement. No customized guidance was overwritten.

Restart an existing librarian MCP server to load the new tools and automatic additive schema upgrade, then invoke `$review-organization` from the library workspace. A new or resumed invocation performs the actual review. Physical placement remains the separate `reorganize --dry-run` / `reorganize` flow.

## Verification

No new unit tests or test tooling were added. Direct behavior checks used isolated
scratch catalogs and scripts under `/tmp/rpg-organization-check/`:

- `check.py`: persisted run resume, assignment through a line alias, rollback of earlier assignments and newly created products on a later failure, durable review storage, rejection memory, and protection of unchanged owner decisions.
- `packs.py`: stale-snapshot rejection without coverage advancement; pack creation with retained history after old entries disappear; removed members assigned through generated references in the same transaction; owner resolution across entry replacement; preservation of an unrelated flag; and catalog-only behavior with no physical files present.
- `edge_check.py`: literal percent/underscore folder matching and the root folder; duplicate recommendation suppression; unchanged coverage staying quiet; mtime-only changes staying quiet; and newly available embedded evidence allowing explained reconsideration.
- `mcp_check.py` and `mcp_ops.py`: actual in-process FastMCP client/server discovery and calls, pagination, typed nested operation/recommendation schemas, atomic pack correction, finding lookup, receipts, rejection resolution, and preservation of an unrelated open question during an automatic pack correction.
- Read-only scan of the current live catalog: **307,513 eligible files**, **19,460 groups**, **5.62 seconds**, about **491 MiB** peak process RSS while retaining per-group fingerprint lists. The live catalog was opened in SQLite read-only mode; no live migration, assignments, review records, or content changes were made during verification.
- `uv run python scripts/check_migrations.py`: fresh migration through 0007 matches SQLModel metadata.
- Ruff lint, formatting (152 Python files), and `ty check`: passed.
- Existing pytest suite: **3 passed**.
- Skill creator validation: both skills passed.
- `uv build --package rpg-librarian`: source distribution and wheel passed; wheel inspection confirmed the new skill, migration, and service are included.
- `git diff --check`: passed.

## Practical limits

The LLM's real-world judgment quality and the usefulness of its recommendations have not yet been evaluated on the live library. Scratch checks verified service behavior using supplied decisions, not an independent LLM organization pass. See [evaluations.md](evaluations.md) for the qualitative rubric assessment.

No organization pass, physical moves, scheduling, commits, or merges were performed. Review continuity is at the group level: interrupted inspection of a group can require re-reading that group, while committed groups retain their coverage. Current whole-pass batch sizing is an implementation choice and can be adjusted through the MCP start tool. Catalog atomicity does not imply filesystem atomicity.
