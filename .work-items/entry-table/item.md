---
name: "Entry table refactor"
status: complete
---

# Entry table refactor

A pure-refactoring infrastructure change that prepares the catalog to treat packs (collections of files) as first-class later. A new `entry` table becomes the identity the MCP tools, evidence, errors, and review flags use, while behavior stays unchanged. This is the prerequisite step split out of [asset-pack-handling](../asset-pack-handling/item.md).

## Documents

- [idea.md](idea.md): workshop outcome of 2026-10-02: the design and the decisions.
- [plan.md](plan.md): the full plan with every step's result: phase 1 and 1b (test preparation and tooling), phase 2 (the refactor), phase 3 (verification and cutover).

## Completion note (2026-10-02)

**Outcome.** The catalog has an `entry` table (`id`, `type` = `file`, `file_id` unique and cascading, `product_id` indexed) and everything that identifies an item now uses entry IDs:
- `product_id` moved from `file` to `entry`; `file` keeps `disposition` (the keep-needs-a-product CHECK is gone, and `update_product` enforces it).
- `google_search_result`, `dtrpg_result`, `rpggeek_result`, `file_text_analysis`, `error`, and `review_flag` are keyed by `entry_id`. `isbn_result`, `file_text`, `file_metadata`, and the media tables stay keyed by `file_id`.
- The MCP tools and CLI take and report entry IDs: `report_entry` (was `report_file`), `update_product(entry_ids)`, `rename-file(entry_id)`, `list_unfiled`, `report_product`. File IDs never reach the LLM, and a file ID given where an entry ID belongs is refused.
- Migration `0005` converts an existing catalog without changing any content, with a working downgrade. Entries are seeded with `entry.id = file.id`, but rows are mapped through `entry.file_id`.
- Server instructions, `describe_schema` notes and examples, and both bundled skills (`process-batch`, `review-items`) use entry IDs; `design-assets` joins the seed product types.

**Verification (all behavior-level, no new unit tests, per the workflow).**
- Smoke library `~/data/rpg_test` (enhanced with permanent fixtures): the full 15-step golden run on the new code is identical to the frozen run of the old code, on a normal copy and on a copy with entry IDs shifted by 100000 (to catch file-ID/entry-ID confusion).
- The catalog, placement, and report comparisons are equivalent on the smoke copy, the shifted copy, and a copy of the full catalog (34,293 files, 34,243 placements byte-identical, 192 sampled reports with 0 differences). The tool-level script passes 37/37 on the normal copy and 41/41 on the shifted copy, and 41/41 and 46/46 when it also runs a real `enrich --limit 1`. Injected defects were caught by each tool.
- The migration round trip (up, down) restores the schema and every row.
- ruff, ruff format, ty, and the migrations check pass.
- The real cutover: the live catalog was backed up twice, migrated to `0005` in 1.6 s, and compared with the backup (EQUIVALENT, placements identical); a new server starts and answers against it.

**Limitations.** The unit-test suite was not touched (none added, per the workflow). The full catalog has no unfiled files still on the share, so the unfiled worklist was exercised on the smoke copy only. `enrich` was exercised with real calls only on `--limit 1`. The migration was not tested against a catalog with a non-file entry type, because none exists yet.

**Where things are.**
- Code: committed on branch `tooling-refactor` (not pushed).
- Live catalog: `~/data/rpg-librarian/catalog.db` at `0005`. Backups: `~/data/rpg-librarian/backups/catalog.pre-entry-table.rawcopy.db` and `catalog.pre-entry-table.db`, plus the old skill files (`*.SKILL.md.pre-entry-table`). Delete them when comfortable.
- Test tooling and snapshots live outside the repo in `~/data/rpg_test_tools/` and `~/data/rpg_test_snapshots/` (including the frozen old-code golden run). The old-code worktree was removed, so the golden run cannot be regenerated from old code.
- Next: [asset-pack-handling](../asset-pack-handling/item.md) can now add `pack` as a second entry type (a new nullable `pack_id` foreign key). Also open: [sanitize-library-filenames](../sanitize-library-filenames/) (registered).
