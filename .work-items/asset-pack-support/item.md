---
name: "asset-pack-support"
status: complete
---

# Asset pack support

Handle map packs, token sets, and audio sets whose folder names carry more identification evidence than their individual filenames or sparse text documents, including packs without external search matches.

## Documents

- [intent.md](intent.md): scope, expected behavior, constraints, acceptance conditions, settled decisions, open questions, and the approved qualitative quality rubric (carried over unchanged from asset-pack-handling). **Current.**
- [idea.md](idea.md): workshop outcome of 2026-10-02: the working direction and reasoning behind it. Superseded by intent.md where they differ.
- [plan.md](plan.md): implementation plan of 2026-10-02 with each phase's result and verification (phases 0 to 8, all done). **Current.**
- [evaluations.md](evaluations.md): qualitative evaluation of the built feature against the rubric.

## Related

- [asset-pack-handling](../asset-pack-handling/item.md) (closed): the earlier version of this item, closed on 2026-10-02 in favor of this one.
- [per-pack-google-lookup](../per-pack-google-lookup/item.md) (complete): one Google search per pack folder at a fixed depth of three.
- [entry-table](../entry-table/item.md) (complete): the `entry` table, so files and, later, packs share one identity for tools, evidence, errors, and review flags.
- [pack-migration](../pack-migration/item.md) (captured): migrates the live catalog to the pack schema and adopts already-filed products as packs. Must run before more processing on live data.

## Completion note (2026-10-02)

**Outcome.** Packs are built as designed in [intent.md](intent.md) and the ten planning
decisions in [plan.md](plan.md):
- Schema: `pack`, `folder_judgment`, `folder_search`, `entry.pack_id` (with a CHECK), and
  `file.pack_id` (RESTRICT), in migration `0006` (with a downgrade that dissolves packs).
- `find-packs`, a new command: catalog-only evidence, the media gate, cached folder-name
  searches, top-down model classification, lossless formation, and `--dry-run`, `--limit`,
  and `--no-search`.
- Placement, `reorganize`, `scan`, `list_unfiled`, the reports, and `update_product` all
  handle packs. There is at most one kept pack per product.
- New MCP tools and CLI verbs: `report-pack`, `create-pack`, `add-to-pack`, and
  `remove-from-pack`.
- Enrichment runs once per pack, with a folder-name ladder and pooled text, and no ISBN.
- The skills, schema notes, server instructions, and README are updated.

Settled during implementation, **not yet confirmed by the user**:
- A dry run's answers are stored, so a later real run forms them without asking again.
- Pack members win the duplicate join, so a loose copy becomes the member's duplicate.
- A member that fails any scan stage is taken out of its pack. That includes a metadata
  or text extraction failure, not only a failed read. A `scan --force` over a pack of
  files the extractors cannot read (some STL files, for example) would pull those
  files out.
- A dissolved pack is never re-formed while its folder is unchanged, and a one-member
  pack never adds new files. Both were fixed after review; see the follow-up in
  [plan.md](plan.md).

**Verification.** Every check is behavior-level; no unit tests were added. Results by phase
are in [plan.md](plan.md):
- ruff, ruff format, ty, and the migrations check are clean.
- Both golden runs (the original, and the new pack-fixture one) are identical on the new
  code.
- On a live-catalog copy, all 34,252 placements are byte-identical to the committed code,
  and reports are identical apart from one new key.
- The migration round trip up to 0006 and back down to 0005 restores the schema and every
  row, on a smoke copy and a live copy.
- New out-of-repo check scripts in `~/data/rpg_test_tools/`:
  - `pack_tool_checks.py`: 42/42, and 42/42 with shifted entry IDs.
  - `pack_reorganize_checks.py`: 15/15.
  - `pack_scan_checks.py`: 16/16.
  - `pack_find_checks.py` (paid): 20/20, and 20/20 with `--no-search`.
  - `pack_skill_sql.py`: 10/10 queries run.
  - `pack_dissolve_checks.py` (offline): 11/11.
  - `pack_e2e.py` (paid): 20/20.
- The existing `tool_checks.py` passes 37/37, 41/41 with shifted IDs, and 41/41 with a
  real `enrich`.

**Limitations.**
- No agent session ran the `process-batch` or `review-items` skills. Filing was scripted
  through the MCP tools in the skill's order.
- `find-packs` was judged only on small, partly fictional fixtures.
- The live catalog has no unfiled files, so the real search and model-call load was not
  measured. That belongs to [pack-migration](../pack-migration/item.md).

**Where things are.**
- Code: uncommitted on branch `tooling-refactor`. The diff also contains the user's
  separate, uncommitted `clear_errors` work (`services/clear_errors.py` and parts of
  `server/tools.py`, `commands/tools.py`, `__main__.py`, and `README.md`).
- Live catalog: untouched, still at `0005`. **It would be migrated to `0006` by any of
  these, run on this working tree:**
  - starting Claude in `~/data/rpg-librarian` (its `rpg-librarian` MCP server runs `uv
    run --project ~/proj/rpg-librarian-mcp rpg-librarian serve` there);
  - running `~/data/rpg-librarian/process-batch.zsh`;
  - any `rpg-librarian` command there (`~/.local/bin/rpg-librarian` uses this
    checkout's virtualenv).

  Back it up first, and wait for pack-migration.
- Test assets live outside the repo:
  - `~/data/rpg_test/dump_four/` (fixtures).
  - `~/data/rpg_test_snapshots/smoke-packs/` and `golden-packs/`.
  - The new and updated scripts in `~/data/rpg_test_tools/`.

**Next.** [pack-migration](../pack-migration/item.md): migrate and adopt the live
catalog's filed products as packs.

**Fix after first live use (2026-10-03, uncommitted).** The first live `find-packs` run
on the inbox judged only 21 folders. It formed 20 packs and left about 51.5k files loose
under `Syrinscape/`, which has 233 subfolders. A folder summary shows the model only the
first 20 subfolders (`SHOWN_CHILDREN`), and the walk descended only into the names in
`descend_into`. `Finder._children` now descends into the named subfolders plus every
subfolder the model was not shown. This also applies when a stored container judgment
is reused. The prompt says that unshown subfolders are always examined.

Verified on a backup-API copy of live (`~/data/rpg_test_work/syrinscape-fix/copy.db`):
- A `--dry-run --no-search --limit 1` run reused the stored `Syrinscape` judgment and
  walked all 232 remaining subfolders: 10 asked and 222 deferred.
- A real `--limit 1` run formed 20 packs over files that already had Google rows and
  text analyses. It deleted exactly those 1,590 member entries' rows, with no
  foreign-key violations and no orphaned rows.
- ruff and ty pass.

## Earlier resume note

The workshop ([idea.md](idea.md)) and a flesh-out session on 2026-10-02 are done, and the result is saved in [intent.md](intent.md). Packs are a second entry type, found by a new `find-packs` command (folder evidence, a media-dominance gate, a cached folder-name search, and a top-down LLM classification). A pack owns its product and disposition, a product has at most one kept pack, and a pack is never re-judged once it exists. Nothing is built. This reverses the entry-table choice to keep `disposition` file-only. Live catalog migration is tracked in [pack-migration](../pack-migration/item.md).

Planning (2026-10-02): [plan.md](plan.md) is written, and the user confirmed its ten planning decisions the same day: tools address members by path; joining deletes the file's entry and normalizes it; filed loose files may be added, with the dropped decisions reported (changed from the proposal); scan behavior for members; members never demoted to duplicates; `RESTRICT` on `file.pack_id`; at most one *kept* pack per product, enforced in services with no index (changed from the proposal); reorganize errors summarized on the pack entry; `folder_judgment` and `folder_search` tables; gate and pooling defaults. Phase 0 records a second golden run and keeps the original one. Tool names: `create-pack`, `add-to-pack`, `remove-from-pack`, `report-pack`. All work runs on copies: the CLI auto-migrates whatever catalog it opens, so the live catalog waits for pack-migration. Precondition: the user's uncommitted `clear_errors` work should be committed first. Next step: implementation, starting at phase 0 (pack fixtures), when the user says to start.
