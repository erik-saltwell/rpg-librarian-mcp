# Pack migration: background and handoff

Written 2026-10-03 for a fresh thread starting pack-migration. It covers what
[asset-pack-support](../asset-pack-support/item.md) built, how it was built and verified,
and the facts and tools the migration needs. The design is
[intent.md](../asset-pack-support/intent.md). The phase-by-phase record, with every check
and result, is [plan.md](../asset-pack-support/plan.md). This document only points into
them.

## Goal of pack-migration

Bring the live catalog to the pack schema. Then turn its already-filed asset products into
packs, before any more processing (scan, enrich, filing) runs on live data. The user's
stated direction (2026-10-02) is to run `find-packs` on each folder under a product line,
with the lossless-formation rule: a pack takes the product and disposition its files
already share. That direction does not work as-is; see "The main open problem" below.

## Safety first: the live catalog

- **Location:** `~/data/rpg-librarian/catalog.db`. It is still at Alembic revision `0005`,
  untouched by asset-pack-support (its hash was checked unchanged at the end). It has
  34,252 present files: 33,109 keep, 762 duplicate, 363 discard, 18 superseded, and
  **0 unfiled**.
- **Opening it with this code migrates it.** `db.session_scope()` upgrades to head by
  default, and `serve` upgrades at startup. Any of these, run on the current working tree,
  would upgrade the live catalog to `0006`:
  - starting Claude in `~/data/rpg-librarian`. Its project MCP server `rpg-librarian`
    runs `uv run --project ~/proj/rpg-librarian-mcp rpg-librarian serve`, with the
    catalog defaulting to `./catalog.db`;
  - running `~/data/rpg-librarian/process-batch.zsh` (scan, enrich, `claude -p
    /process-batch`, reorganize, `claude /review-items`);
  - any `rpg-librarian` command there. `~/.local/bin/rpg-librarian` runs from this
    checkout's `.venv`.
- **Rehearsed:** migrating a live copy 0005 → 0006 → 0005 took 0.7 s. Rows and schema
  were identical after the round trip. Before the real run, back up the catalog the way
  entry-table did (a raw copy plus a copy), as described in
  [entry-table/item.md](../entry-table/item.md).
- **Existing backups** in `~/data/rpg-librarian/backups/` are from the entry-table
  cutover (`catalog.pre-entry-table*.db`).

## What exists now (asset-pack-support, complete, uncommitted)

The code is uncommitted on branch `tooling-refactor`. The diff also holds the user's
separate, uncommitted `clear_errors` work.

| Piece | Where (under `apps/rpg-librarian/src/rpg_librarian/`) |
|---|---|
| Schema: `pack`, `folder_judgment`, `folder_search`, `entry.pack_id` (with CHECK `ck_entry_one_item`), `file.pack_id` (RESTRICT). Downgrade dissolves packs into file entries with the pack's product and disposition. | `model/Pack.py`, `model/FolderJudgment.py`, `model/FolderSearch.py`, `alembic/migrations/versions/0006_add_packs.py` |
| Membership rules: join, detach, delete-if-empty (records dissolved folders), own-entry | `membership.py` |
| `find-packs`: catalog-only folder tree, gate, fingerprints, evidence, model call, walk, formation | `find_packs/evidence.py`, `find_packs/judge.py`, `commands/find_packs.py` |
| Pack tools: `create-pack`, `add-to-pack`, `remove-from-pack`, `report-pack` | `services/packs.py`, `server/tools.py`, `commands/tools.py` |
| A pack's derived current root and member counts | `services/pack_info.py` |
| Placement and `reorganize` for members; pack-aware lists, reports, `update_product`, scan, enrich | see [plan.md](../asset-pack-support/plan.md) phases 2 to 7 |

Rules that matter for migration:
- **A pack owns the disposition.** Its entry holds the product. A member's own
  `file.disposition` is kept `unfiled` and ignored. A member has no entry, so joining a
  pack deletes the file's entry together with its evidence, text analysis, errors, and
  review flags.
- **Lossless formation (`find-packs`):** a folder becomes a pack only if all its eligible
  files are unfiled, or all are filed to the same product with the same disposition. Then
  the pack takes that decision. Otherwise the folder is recorded as `mixed` and left
  alone.
- **At most one *kept* pack per product.** This is enforced in `update_product`,
  `create-pack`, `add-to-pack`, and `find-packs`. A superseded pack may share the
  product.
- **No re-judging.** A pack is never re-judged once it exists. A dissolved pack is never
  re-formed while its folder is unchanged.
- **Automatic duplicates are never members.**
- **Placement:** a kept pack's members are placed under `<type>/<line>/<product>/`, with
  paths relative to the pack's current root (the deepest folder holding its members).
  That is the existing layout of filed library products, so adopting a filed product as a
  pack should not move its files. **This is unverified on live data.**

## The main open problem: `find-packs` will not adopt filed products

`find-packs` only considers *unsettled* folders: folders with at least one unfiled,
eligible file. Every live file is filed, so a `find-packs --dry-run` on a live copy asked
the model nothing. The user's direction therefore needs new behavior. One option, not
designed and not agreed: an adopt mode that also treats folders whose files share one
product and disposition as candidates, and runs them through the same gate, model, and
lossless formation.

Open questions for the migration thread:
- **The adopt mode itself.** Does it go through the model, or follow a deterministic
  rule? In library layout `<type>/<line>/<product>/` is already the product. Restrict it
  to product folders? Skip the search and model calls when a folder's files already
  share one product (a cost saving the user asked about)?
- **Real load.** The real search and model-call load on the live catalog was never
  measured, because nothing was asked. There are 4,412 folders in total, 2,685 of them at
  depth 3.
- **What adoption deletes.** Each adopted file loses its entry rows: old per-file Google
  rows, text analysis, errors, and review flags. This needs a decision on whether that
  loss is acceptable or must be carried over to the pack.
- **Verification plan.** Placements must stay unchanged, or change only as intended,
  after adoption.

Unconfirmed asset-pack-support decisions that may matter here (listed in its
[item.md](../asset-pack-support/item.md)):
- A dry run's stored answers are formed by the next real run without asking again.
- Pack members win the duplicate join.
- A member that fails *any* scan stage, including metadata extraction, is taken out of
  its pack. A `scan --force` over packs of unreadable STL files would split them.

## How asset-pack-support was built and verified (the process to reuse)

1. **Fixtures first (phase 0).**
   - Permanent pack-shaped fixtures were added in `~/data/rpg_test/dump_four/` by
     `add_fixtures.py`.
   - A pack baseline was built with `build_smoke.py --packs` and snapshotted as
     `~/data/rpg_test_snapshots/smoke-packs`.
   - A second golden run was recorded as `golden-packs`. The original `golden` run, on
     pre-entry-table code, was kept untouched.
2. **Schema plus migration (phase 1).**
   - `scripts/check_migrations.py`.
   - `migrate_copy.py` up and down on a smoke copy and a live copy.
   - `rows_equal.py` and `schema_diff.py` to compare the results.
   - A hand-made pack to test the downgrade.
3. **Pack-aware readers with no packs yet (phase 2).** Loose-file behavior was proven
   unchanged:
   - both golden runs IDENTICAL with `diff_runs.py`;
   - on a live copy, placements byte-identical between the committed code (a temporary
     `git worktree` of HEAD) and the new code;
   - sampled reports identical apart from one new key.
4. **Each feature with its own check script** (phases 3 to 8, all in
   `~/data/rpg_test_tools/`):

   | Script | What it checks | Result |
   |---|---|---|
   | `pack_tool_checks.py` | the pack tools | 42/42, also with `--prepare offset` |
   | `pack_reorganize_checks.py` | `reorganize` with packs | 15/15 |
   | `pack_scan_checks.py` | scan with packs | 16/16 |
   | `pack_find_checks.py` (paid) | `find-packs` | 20/20, also with `--no-search` |
   | `pack_skill_sql.py` | every skill and schema SQL block | 10/10 |
   | `pack_e2e.py` (paid) | end to end | 20/20 |
   | `pack_dissolve_checks.py` (offline, stub model) | corrections survive | 11/11 |

5. **Finish.** All suites were re-run after every fix, and the live hash was checked
   unchanged.

Verification policy for this project: no unit tests. Use behavior-level checks on copies
only.

## Tools to reuse (all in `~/data/rpg_test_tools/`)

- **Copies and comparison:**
  - `migrate_copy.py SOURCE OUT [--to REV]` uses the project's Alembic and refuses the
    live catalog.
  - `rows_equal.py` and `schema_diff.py` compare rows and schemas.
  - `compare_catalogs.py` and `catalog_state.py` now key pack entries as
    `pack:<root>`/`<original root path>` and report `packs` only when some exist.
  - `snapshot_placements.py` drops a None `pack_id`.
  - `snapshot_reports.py` captures reports.
- **Live snapshots:** `snapshot_before.py full` writes the live snapshot to
  `rpg_test_snapshots/full/`. That snapshot is from before entry-table, at `0004`, so a
  fresh one at `0005` will be needed. `guarded_run.py` refuses the live catalog and limits
  where catalogs may sit.
- **Smoke state:** `restore_smoke.py --snapshot smoke-packs` restores
  `~/data/rpg_test_work`. `golden_ops.py --snapshot NAME --out DIR --no-code-check` runs
  the golden operations, and `diff_runs.py` compares two runs.
- **Offline `find-packs`:** to try it without paid calls, replace
  `rpg_librarian.commands.find_packs.judge` with a stub and pass `no_search=True`. See
  `pack_dissolve_checks.py`.

Gotchas seen while building:
- Scan walks folders in sorted order, so the first-sorted copy of identical files is the
  original. In the fixtures, `Downloads Again/Goblin Warband Token Pack` is the real pack
  and the other copy was trashed as duplicates.
- The baseline has one permanently blocked file (Play Dirty). Expect it in `reorganize`
  output and pending counts.
- The shell is zsh: an unquoted variable is not word-split (use `${=var}`).
- The paid fixture runs cost a few model calls and searches each.
