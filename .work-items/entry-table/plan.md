# Entry table refactor: plan

Scope: **phase 1** (preparing the tests), **phase 1b** (test tooling that depends on the
refactor), **phase 2** (the refactor and its migration), and **phase 3** (verification
with the phase 1b tools). Design and decisions are
in [idea.md](idea.md); this plan does not repeat them.

## Phase 1: prepare the tests

**Goal:** before any refactor code is written, have on the current code a rebuildable
smoke-test catalog covering all seven agreed fixture items, "before" snapshots for the
smoke catalog and for a copy of the live catalog, and proof that the compare tooling works
on both. No repo changes in this phase; all new scripts live in `~/data/rpg_test_tools/`.

Facts relied on (checked 2026-10-02): every CLI verb takes `--catalog`; API keys are in
the repo's `.env`, so commands run from the repo root as
`uv run --project apps/rpg-librarian rpg-librarian … --catalog <path>`; `init --library`
creates the library root and `add-source` registers each dump as a staging root (no
nesting); Pillow 12.3 and ffmpeg are available; the live catalog is at alembic `0004`
with two roots, both present on disk.

### Steps

- [x] **1. Pristine source, working copy.** `build_smoke.py` deletes and recreates
  `~/data/rpg_test_work/`, copies the dumps from `~/data/rpg_test` into it, and creates an
  empty `Library/`. `reorganize` really moves files, so the smoke test never runs on
  `~/data/rpg_test` itself.
  Done 2026-10-02: `~/data/rpg_test_tools/build_smoke.py`. It only deletes a working tree
  holding its own `.rpg-smoke-work` marker and refuses one overlapping the source.
  Verified: two consecutive runs succeed; the source's file hashes are unchanged; the copy
  is byte-identical to the source (55 files: `dump_one` 7, `dump_two` 2, `dump_three` 46);
  `Library/` is empty; an unmarked directory and a path inside the source are refused.
- [x] **2. Fixtures (items 3, 5, 6, 7).** Changed by the user on 2026-10-02: the static
  fixtures are added **permanently to `~/data/rpg_test`** instead of being generated into
  each build, so they can be browsed and `build_smoke.py` simply copies them. Made by the
  idempotent `~/data/rpg_test_tools/add_fixtures.py` (run under `uv run --project
  apps/rpg-librarian` for Pillow); action fixtures stay in `build_smoke.py` (steps 3-4).
  Done 2026-10-02; `rpg_test` went from 55 to 63 files:

  | Fixture | Path (under `~/data/rpg_test`) | Checked |
  |---|---|---|
  | Automatic duplicate | `dump_two/Blood and Bone/Core Rules/Fasano-BloodAndBone.pdf` | Same SHA-256 as the `dump_one` original |
  | Zero-byte PDF | `dump_three/Old-School Essentials/Extras/OSE Quick Reference.pdf` | PyMuPDF: `EmptyFileError` |
  | Corrupt PDF (first 4 KB of `Lies2e.pdf`) | `dump_three/.../The Temple of Lies/Lies2e-preview.pdf` | PyMuPDF: `FileDataError` |
  | Truncated OGG (first 64 KB of `Battle 1.ogg`) | `dump_three/.../Cyberpunk Music Pack/BGM/Battle 4.ogg` | **Not an error:** mutagen and ffprobe read it as a valid 3.3 s clip |
  | PNG, JPEG, WebP (800x600, Pillow-drawn) | `dump_two/Handouts/Sunken Temple/` | Open with Pillow; distinct hashes |
  | Awkward filename (altered copy of `TCS001.pdf`) | `dump_one/books/GM Advice/Café Noir: Who Killed the Ĝnome?.pdf` | Opens (39 pages, as the original); different hash, so not a duplicate |

  Also verified: a second run creates nothing; all 55 original files are byte-unchanged;
  `build_smoke.py` copies all 63 files identically into `rpg_test_work`.

- [x] **3. Round 1.** `init` and `add-source` for the dumps, `scan`, `enrich` (all
  sources), a fixed `update-product` sequence, then a real `reorganize`, filling
  `Library/` and storing subpaths (item 1). Implemented in `build_smoke.py` itself (stage
  `round1`), not a separate `file_smoke.py`: one command builds the baseline. It resolves
  file IDs by path through a read-only query and files whichever copy of the duplicate
  scan did not mark. It is run on the current code when creating or refreshing the
  baseline, not for every test run (agreed 2026-10-02); `--stop-after tree` and
  `--skip-enrich` exist for iterating.

  Done 2026-10-02 (full run about 7 minutes, mostly `enrich`). Result:
  - 63 files: keep 46, unfiled 11 (10 flagged Battlefinder maps, `Play Dirty` left
    unfiled on purpose), discard 3, superseded 2, duplicate 1.
  - Filing covered: single-file and multi-file `keep` (including nested subfolders and
    images), a second product in an existing line, product metadata, line aliases,
    `superseded` with and without coordinates, `discard` (corrupt and zero-byte PDFs), an
    open flag on 10 files, a flag resolved by `keep` with `--note`, and a discard that
    keeps its product link (`update_product` clears the link only for `unfiled`; 2 non-kept
    files keep a link, including one superseded).
  - `reorganize`: 46 moved into `Library/`, 6 to `.trash/` (discarded, duplicates,
    superseded), 0 blocked, 0 errors; all 46 kept files have a stored `subpath`.
  - Errors: 2 at stage `metadata`, from the zero-byte and corrupt PDFs.
  - Evidence: Google 62 rows, DriveThruRPG 23, RPGGeek 23, ISBN 4 (all empty), text
    analysis 28 (1 empty), `image_metadata` 3.
  - Side effects of the current code, not fixtures: `init` installs 6 bundled skill files
    under `Library/.claude`, `.codex`, `.gemini`, and the app writes `logs/events.log`
    next to the catalog.
  - Observation: `sanitize_name` cleans the line folder (`Café Society- Noir`), but a
    single-file product keeps its original filename, so
    `Café Noir: Who Killed the Ĝnome?.pdf` lands in the library with `:` and `?`. That is
    existing behavior, unchanged by this refactor; it would fail on a Windows share.

- [x] **4. Round 2.** Stage `round2` of `build_smoke.py`. Round 2 files are created by
  the script (altered copies, so not duplicates) in a new `round2/` staging root:
  `ArdensLudere-TheSprawl-Errata.pdf`, `TCS002.pdf`, `Fasano-BloodAndBone-Errata.pdf`, and
  `Unsorted/Lies2e-draft.pdf` (never filed; added during step 5, see there). The
  kept library file `Miniature Holder/No Supports/Slider.stl` is deleted before the scan
  (missing). After scan, enrich, and filing, a stray untracked file is placed at the
  library path `Play Dirty` wants, then a real `reorganize`; finally the Blood and Bone
  errata is filed so moves remain pending.

  Done 2026-10-02 (whole build about 8.5 minutes). Result:
  - Filed: a file added to a multi-file product already in the library (The Sprawl), a
    single-file library product turned multi-file (Fastlane: `TCS001.pdf` moved from
    `games/Fastlane/` into `games/Fastlane/Fastlane/`), and `Play Dirty`.
  - `reorganize`: 3 moved, 50 already in place, 1 blocked (`Play Dirty`: "something
    already exists at the destination"), leaving an error row at stage `reorganize`.
  - Pending (dry run): 2 to move (the Blood and Bone original moving into its new product
    folder, plus the errata), 1 blocked, 52 in place.
  - Catalog after the step 5 rebuild: 67 files (keep 50, unfiled 11, discard 3,
    superseded 2, duplicate 1); 1 missing; 10 open and 1 resolved flags; errors
    `metadata` 2 and `reorganize` 1; Google 66, DriveThruRPG 27, RPGGeek 27, ISBN 5, text
    analysis 32, `image_metadata` 3; 48 kept files with a stored subpath; 2 non-kept
    files with a product link.

- [x] **5. Coverage report.** `~/data/rpg_test_tools/coverage_smoke.py` (read-only,
  stdlib-only, pre-refactor schema) runs 36 checks grouped by fixture item and exits 1 if
  any is missing. Agreed 2026-10-02: the "no-match row" of item 4 counts as covered by an
  empty-result row in at least one re-keyed table. The available empty rows are 9 in text
  analysis (no description and no or `unknown` system); Google, DriveThruRPG, and RPGGeek
  found hits for every file. An empty row is re-keyed like any other, and the compare
  script checks every row's content.

  Done 2026-10-02. The first run found two gaps, fixed before rebuilding:
  - **No unfiled file without a flag:** round 2 files `Play Dirty` (for the collision),
    leaving only flagged unfiled files. Fixed by adding a never-filed round 2 file,
    `round2/Unsorted/Lies2e-draft.pdf`.
  - **A wrong proxy for pending library moves:** the check looked for kept library files
    without a stored subpath, but `update_product` keeps the subpath when the product does
    not change, so the Blood and Bone original (whose product became multi-file) still has
    one. Replaced by a direct check for a library file still flat in its line folder whose
    product now has several kept files.

  After a full rebuild with enrich, all 36 checks are present.

  **Repeatability checked 2026-10-02** (phase verification item): the final build script
  ran twice in a row, each time with a real enrich. The coverage report output was
  identical. So was a fingerprint of the catalog: every file's root, path, disposition,
  missing flag, subpath, and product coordinates; every error row by file and stage; every
  review flag with its reason and resolution; evidence row counts and empty-result counts
  per table; and product, line, and alias lists. Evidence content (search hits, LLM
  descriptions) is not part of the fingerprint, because it can legitimately differ between
  paid runs; it is frozen by the step 6 snapshot instead.

- [x] **6. "Before" snapshots** in `~/data/rpg_test_snapshots/`. Smoke: catalog copy,
  placements, `reorganize --dry-run` output, JSON from `report-file`, `report-product`,
  `report-line`, `list-unfiled` for fixed IDs and folders, and a **full copy of the
  `rpg_test_work/` tree** (`smoke-tree/`, about 290 MB; agreed 2026-10-02). The catalog
  stores absolute paths under `rpg_test_work`, and `reorganize --dry-run` and
  `rename-file` read the disk, so later test runs restore this tree together with the
  catalog copy; a rebuild of `rpg_test_work` would otherwise put files back in the dumps
  and invalidate those checks. Full: a copy of the live catalog taken while nothing runs against it,
  its placements, `--dry-run` output on the copy only, and the live file's SHA-256.

  Done 2026-10-02, in `~/data/rpg_test_tools/snapshot_before.py smoke|full` (with
  `snapshot_reports.py` for the read-tool outputs and the existing
  `snapshot_placements.py`). It refuses to overwrite a snapshot that already has content.
  Both were taken on the pre-refactor code (branch `tooling-refactor`, HEAD `bf88dc3`, no
  uncommitted changes under `apps/` or `packages/`, alembic revision `0004`; recorded in
  each `manifest.json`).

  - **Smoke** (`~/data/rpg_test_snapshots/smoke/`, 292 MB): `catalog.db`, the full
    `tree/` (76 files: library, trash, dumps, `round2/`, logs, installed skills), 55
    placements, the dry-run output (2 to move, 1 blocked, 52 in place, as the build
    reported), and reports for all 67 files, 14 products, 12 lines, plus the unfiled
    listings. The working catalog's hash was unchanged by the placement and dry-run
    commands.
  - **Full** (`~/data/rpg_test_snapshots/full/`, 545 MB): a copy of the live catalog, 34,243
    placements, dry-run output, and sampled reports (131 files, 28 products, 28 lines:
    up to 8 files per disposition and media type, every file with an error, evenly spaced
    products and lines plus the largest). The live file's SHA-256 was identical before the
    copy, after it, and for the copy:
    `0bd57afa75865e1898328b01a4835eb86869a1779f977e2c542a5ced0efcd324`, also saved in
    `full/live.sha256` for the end-of-phase check.
  - **Notes.** The MCP server (`rpg-librarian serve`, running since Oct 1 from
    `~/data/rpg-librarian`) was left running; it holds no open connection, and the
    catalog had no WAL or journal file and was last written Oct 1 17:21. The full dry run
    reports "0 to move, 34,243 already in place", which confirms why the placement diff
    is the primary check. The app wrote a `logs/` directory beside the copied catalog
    (`full/logs`, a side effect of the current code, harmless).
  - The `dry-run.txt` files were captured from stdout only. In the smoke snapshot the
    catalog's disk paths point at `rpg_test_work`, so restoring `tree/` there is what
    makes a later dry run valid.

- [x] **7. Compare rehearsal.** Save the hand-built simulated migration as
  `simulate_migration.py`; run it on copies of both snapshots; `compare_catalogs.py` with
  placements must report EQUIVALENT, and an injected defect must still fail.

  Done 2026-10-02, with `~/data/rpg_test_tools/simulate_migration.py SOURCE OUT`. It
  copies a catalog and applies the design in plain SQL (stdlib only): `entry` with
  `UNIQUE (file_id)`, an index on `product_id`, seeded `id = file.id`, and `product_id`
  copied for every file; `file` rebuilt without `product_id`, its index, and the CHECK; the
  six tables renamed to `entry_id`; then `foreign_key_check` and `integrity_check`. This
  replaced the earlier hand-built simulation that kept `file.product_id`, so the compare
  script's structure check now runs for real, with no `--skip-product-move-check`. Review
  finding 1 (entry constraints) is included and was approved by the user on 2026-10-02;
  finding 2 (copy every product link) is an observation included in the rehearsal.
  - **Equivalence.** Both snapshots compare EQUIVALENT: smoke (67 files, 67 entries, 52
    with a product) and full (34,293 files, 33,325 entries with a product: 33,109 keep +
    198 discard + 18 superseded). The comparison takes about 4 seconds at full scale.
  - **Injected defects.** On the smoke rehearsal, 9 of 10 were caught, including the
    fixture-specific cases: a non-kept file's product link not copied, a scan error row
    re-pointed to the wrong entry, a resolved flag reopened, a lost `duplicate_of_id`, a
    cleared missing flag, a changed subpath, an altered empty text-analysis row, an entry
    type other than `file`, and a lost file-keyed `isbn_result` row. The tenth, a second
    entry for one file, was refused by the `UNIQUE (file_id)` constraint before the compare
    could run (finding 1 enforces it). On the full rehearsal, 5 of 5 single-row defects
    were caught out of tables of 198 to 33,491 rows.
  - **Limit.** The placements comparison here is a plumbing check only: the "after" file is
    the "before" file, because the new code that would write a real "after" does not exist.
    It will be exercised for real in the migration phase.

- [x] **8. Diverging ID spaces (added 2026-10-02; review finding 5).**
  `~/data/rpg_test_tools/renumber_entries.py SOURCE OUT`: on a copy of a migrated catalog,
  add an offset (default 100,000) to every `entry.id` and to `entry_id` in the six
  re-keyed tables, then run `foreign_key_check` and `integrity_check`. Rehearse it on the
  simulated migrations of both snapshots: `compare_catalogs.py` must still report
  EQUIVALENT (it matches by path; the offset copy should report 0 entry ids equal to file
  ids), and a mutation that sends a file ID where an entry ID belongs must be caught.
  Later, after the real migration exists, the tool-level checks (`report_entry`,
  `update_product`, `list_unfiled`, `rename-file`) run against both the normal and the
  offset copy.

  Done 2026-10-02: `~/data/rpg_test_tools/renumber_entries.py SOURCE OUT [--offset N]`
  (default 100,000; it refuses an offset not above the highest entry id, an existing
  output, or an unmigrated source, and deletes its output on any failure).
  - **Equivalence.** On the simulated migrations of both snapshots, the offset copies pass
    `foreign_key_check` and `integrity_check`, and `compare_catalogs.py` reports
    EQUIVALENT with structure passing and **0 of 67** (smoke) and **0 of 34,293** (full)
    entry ids equal to their file ids.
  - **Mutations, all caught on both snapshots:** an evidence row, an error row, and a
    review flag written under a file id (matching no entry); an evidence row landing on a
    different existing entry; and a product set on the wrong entry.
  - **Fidelity fix to step 7's simulation.** The offset tool's foreign-key check showed
    `simulate_migration.py` had only renamed the six tables' `file_id` columns, leaving
    their foreign keys pointing at `file (id)`. It now rebuilds those tables so the key
    targets `entry (id)`, as the real migration will. Step 7's results still hold: after
    the change both snapshots rehearse EQUIVALENT with the same checks.
  - **For the real migration:** the open-flag index kept its old name
    `ix_review_flag_open_file_id` (it is on `entry_id` and keeps its `WHERE resolved_at
    IS NULL`); the real migration should rename it, for example to
    `ix_review_flag_open_entry_id`.
  - The tool-level checks (`report_entry`, `update_product`, `list_unfiled`,
    `rename-file`) against the normal and offset copies were done in phase 1b step 14.

### Phase 1 verification

All done 2026-10-02:

- The coverage report shows every item present (36 of 36).
- `build_smoke.py` run twice gives the same coverage and the same catalog fingerprint.
- The compare rehearsal is EQUIVALENT on both snapshots and fails on injected defects
  (see step 7).
- The live catalog's SHA-256 is unchanged:
  `0bd57afa75865e1898328b01a4835eb86869a1779f977e2c542a5ced0efcd324` now, the same as
  recorded in `full/live.sha256`.
- `git status` shows no changes to code: only the work-item files (`.work-items/`,
  `WORK-ITEMS.md`) differ.

### Unknowns (all resolved)

- RPGGeek and DriveThruRPG returned hits for every file (step 5 saw no empty rows in
  those tables; the agreed empty-row coverage comes from text analysis).
- The zero-byte and corrupt PDFs do produce scan error rows (stage `metadata`, 2 rows). The
  truncated OGG reads as a valid short clip and produces none; the user did not ask for an
  unreadable audio file.
- Review finding 5 (diverging ID spaces) was agreed and built as step 8; finding 1 was
  agreed.

## Phase 1b: test tooling that waits on the refactor

Added 2026-10-02 after the user asked whether the smoke test and the full-database run
could start once the refactor is implemented. Answer: the database comparison is ready;
the checks that run the new code are not. These steps close that gap. Steps 9 to 11 need
nothing from the new code and were built on 2026-10-02; steps 12 to 14 depend on the names
the refactor introduces (`report_entry`, entry IDs, renamed fields) and are finished
alongside it. Not started.

- [x] **9. Restore script.** `~/data/rpg_test_tools/restore_smoke.py`: put the saved
  `smoke/tree/` and `smoke/catalog.db` back at `~/data/rpg_test_work/` byte-identically,
  so a run can be repeated. The catalog stores absolute paths into that directory, so two
  runs cannot share the disk at once; they run one after the other, restoring between.
  Verify by hashing the restored tree and catalog against `smoke/manifest.json`.

  Done 2026-10-02: `~/data/rpg_test_tools/restore_smoke.py` (`--verify` only compares).
  Restoring deletes `rpg_test_work/` (only a tree carrying the build marker), copies the
  snapshot tree with modification times, then verifies every file by path, size, mtime, and
  SHA-256, plus the catalog and the file listing against `smoke/manifest.json`. Restoring
  twice is idempotent. Five injected defects were each caught (a deleted file, a
  same-size content change, a changed mtime, an extra file, a changed catalog), and an
  unmarked directory is refused. The working tree was found to differ from the snapshot only
  by `logs/events.log`, which later commands had appended to.

- [x] **10. Golden runs of the old code.** Rather than keeping an old checkout in play for
  every later comparison, run the old code (commit `bf88dc3`, from a separate worktree
  outside the repo) once against the restored smoke state and freeze the outcomes: the
  catalog fingerprint and a path-and-size listing of the tree after a real `reorganize`,
  and the results of a fixed list of operations (`update_product`, `rename-file`, a scan
  of new files, a content change). `enrich` is excluded: it is paid and its results vary.
  The new code must reproduce these, apart from expected renames. Creating the worktree
  adds an entry to the repo's git worktree metadata; it is removed when the golden runs
  are done.

  Done 2026-10-02, with three tools in `~/data/rpg_test_tools/`:
  - `catalog_state.py`: a canonical description of a catalog, keyed by root path and
    relative path, never by id, working on both the old and the new schema (it reuses the
    compare script's id mapping). It leaves out timestamps and reduces a flag's
    `resolved_at` to whether it is set.
  - `golden_ops.py --out DIR [--project CHECKOUT] [--no-code-check]`: restores the smoke
    state, then runs 12 operations, recording `state.json`, `tree.json`, and `output.txt`
    after each (plus `00-restored`): `reorganize` three times; `update-product` to file a
    new arrival into an existing product, resolve flags with a note, supersede a kept
    file, unfile a kept file, and flag a kept file; `rename_file` on a kept file (catalog
    only: `on_disk` false) and on an unfiled file (on disk); a `scan` of two new files (one
    an exact duplicate); and a content change followed by `scan`. Files are named by path
    and ids are looked up per step (a file id, or on the new schema the entry id).
  - `diff_runs.py A B [--outputs]`: compares two runs step by step.
  The frozen golden run is `~/data/rpg_test_snapshots/golden/` (1.5 MB, with `run.json`
  recording commit `bf88dc3` and a clean `apps/` and `packages/`). Two further runs were
  IDENTICAL to it in all 13 steps, including the command output, and injected differences
  in a state file and a tree file were reported. After the runs the working tree is
  restored to the snapshot.
  - **Deviation from the plan:** no separate worktree was needed. The checkout is still at
    `bf88dc3` with no code changes, so the runner checks that and uses it directly; when the
    refactor has changed the checkout, `--project` can point at a worktree of `bf88dc3` (and
    the new code is run with `--no-code-check`). `rename-file` has no CLI verb, so the runner
    calls its service in-process as the MCP tool does. `enrich` is excluded, as planned.
  - **Observation (existing behavior, now recorded as golden):** after a content change,
    `scan` resets the file to unfiled with no product but leaves its old `subpath`. The new
    code must reproduce this, or the difference must be a decision.
  - Golden step `07-reorganize` also showed `reorganize` moving a product's remaining file up
    a level once the other file was unfiled (Fastlane): the golden file layout depends on
    the order of the operations.

- [x] **11. Live-catalog guard for the full run.** A wrapper that runs a command only on
  `~/data/rpg_test_snapshots/full/catalog.db` or a copy of it and refuses any path equal
  to `~/data/rpg-librarian/catalog.db`, a symlink to it, or a catalog whose recorded
  source is the live file without the copy marker; and re-hashes the live file against
  `full/live.sha256` afterwards. It also refuses `reorganize` without `--dry-run` on the
  full copy (its roots point at `/phinneas/...`). Reason: CLI commands auto-migrate the
  database they open, so the new code run against the live file would migrate the real
  catalog.

  Done 2026-10-02: `~/data/rpg_test_tools/guarded_run.py --catalog DB -- VERB ARGS`
  (importable `check_catalog` and `check_verb` for in-process scripts). Refuses, running
  nothing and exiting 2: the live catalog by path, by symlink, or by hard link (device and
  inode); a catalog outside `~/data/rpg_test_snapshots/`, `~/data/rpg_test_work/`, or the temp
  directory; `serve`; a second `--catalog` in the command; a missing recorded live hash; and a
  live file that no longer matches `full/live.sha256` (stale baseline). On a catalog with
  any root outside `rpg_test_work` (the full copy) it allows only `report-*`, `list-*`,
  `update-product` (database only), and `reorganize --dry-run`. It hashes the live file before
  and after, and exits 3 if it changed during the run. Also sets `RPG_LIBRARIAN_CATALOG` to
  the chosen copy so nothing can fall back to another catalog.
  - Verified: all refusals above (the hard link against a stand-in "live" file), `reorganize`,
    `scan`, `enrich`, `init`, and `add-source` refused on the full copy; `list-types` and
    `reorganize --dry-run` (0 to move, 34,243 in place) allowed and the live hash unchanged;
    the alarm fired (exit 3) when a stand-in live file was modified during a run; all verbs
    except `serve` allowed on a catalog whose roots are under `rpg_test_work`.
  - **Deviation:** the plan's "recorded source is the live file without a copy marker" rule was
    replaced by the allowed-folders and same-file checks, which are checkable.
  - A first version silently skipped the stale-baseline check when the recorded hash was
    missing; it now refuses (fail closed).

- [x] **12. Snapshot scripts for the new code** (after the refactor).
  `snapshot_placements.py` and `snapshot_reports.py` updated for the new names
  (`Placement` fields, `report_entry`, entry ids found through `entry.file_id`), keeping
  paths as the match key.
  - Done 2026-10-02. Both scripts now work on either schema, so one copy serves old and
    new code. `snapshot_placements.py` also drops `entry_id`. `snapshot_reports.py`
    detects the `entry` table; on the new schema it reports each file by entry id through
    `report_entry`, counts products and lines through `entry.product_id`, finds errored
    files through `error.entry_id`, and writes `"id_kind": "entry"` in `index.json` (the
    old-schema output is unchanged). Files are still chosen by file id on both schemas, so
    `--sample` picks the same files either way.
  - Verified: run with the old code on copies of the "before" catalogs, both scripts
    reproduce the saved snapshots byte for byte (smoke and full placements, smoke reports,
    full `--sample` reports). Run with the new code on migrated copies: placements are
    byte-identical to the "before" files for smoke (55), the offset smoke copy (55), and
    full (34,243). The reports select the same files (by path), products, lines, and list
    files as "before" (67/14/12 smoke, 131/28/28 full); each file report's `entry.id`
    equals its file name and its path matches the index (ids from 100001 on the offset
    copy); no report mentions `file_id`. The new outputs are in `/tmp/s12/`
    (`rep_smoke`, `rep_smoke_off`, `rep_full`, `pl_*.json`) for step 13; regenerate them
    if `/tmp` has been cleared.
- [x] **13. Report comparison** (after the refactor). `compare_reports.py`: match the
  saved "before" outputs (`smoke/reports`, `full/reports`) with the new ones by root path
  and relative path, and allow only the expected differences (`file_id` to `entry_id`,
  tool and field renames, the new entry id); any other difference fails.
  - Done 2026-10-02: `~/data/rpg_test_tools/compare_reports.py BEFORE_REPORTS AFTER_REPORTS
    --before-db BEFORE.db --after-db AFTER.db`. It reads both catalogs (read-only) to map
    each old file id to the entry id of the same path, rewrites each "before" document
    with exactly the intended differences, and requires an exact match with the "after"
    document. The intended differences: `files/<id>.json` named by entry id; `file.id`
    becomes `entry: {id, type: "file"}`; `duplicate_ids` becomes `duplicate_entry_ids`;
    `duplicate_of.id` becomes `entry_id`; `files[].id` becomes `files[].entry_id` in
    product reports and unfiled lists; `index.json` keyed by entry id with `id_kind`. It
    also fails if `file_id` appears anywhere in the new output. Nothing else may change:
    products, lines, types, roots, evidence, errors, flags, hints, counts, ordering, and
    timestamps all compare exactly.
  - Verified: EQUIVALENT with 0 differences on smoke (102 documents), the offset smoke
    copy (102), and full (192 sampled documents). Injected defects, each caught: a changed
    product id, a file id (not an entry id) in a product list, a file id in
    `duplicate_of`, an extra key, a missing report, and a `file_id` leak.
- [x] **14. Tool-level checks** (after the refactor), scripted and run on the normal
  migrated smoke copy and on its offset-renumbered copy:
  - scanning new files creates an entry per file;
  - a content change clears `entry.product_id`;
  - `update_product` with entry IDs works, and file IDs on the offset copy fail loudly;
  - `rename-file` works on a file entry and rejects an unknown entry;
  - `list_unfiled` and `report_entry` return entry IDs;
  - a real `reorganize` on the restored smoke state matches the golden run from step 10;
  - `enrich` writes entry-keyed rows (a small run with `--limit`).
  - Done 2026-10-02: `~/data/rpg_test_tools/tool_checks.py [--prepare offset] [--enrich]`,
    run with the new project's Python. It restores the smoke state, migrates, optionally
    renumbers entries (+100000), then drives the real MCP tools in-process (FastMCP's
    in-memory client) and the real CLI, checking the catalog after each. It also checks that
    a refused call leaves every row of every table unchanged (a hash of the whole catalog),
    that `file` has no `product_id`, and that foreign keys are clean.
  - Verified: 37/37 checks on the normal copy and 41/41 on the offset copy; with `--enrich`
    (real calls, `--limit 1`) 41/41 and 46/46, rows keyed by offset entry ids, no orphans.
    Coverage: tool surface; entry ids in `list_unfiled` and `report_entry` matching the path
    shown, with no `file_id` in output; unknown ids, keep without a product, and (offset) file
    ids refused with the catalog unchanged; `update_product` puts the product on the entry and
    the disposition on the file, and a review flag opens on the entry; `rename-file` by entry
    id (and unknown id, file id on the offset copy, refused); scan makes one entry per new
    file with fresh ids above the maximum; a content change clears `entry.product_id` and
    its entry-keyed evidence but keeps the entry id; `reorganize` leaves unsettled only
    files that have a reorganize error naming an entry.
  - Injected defects, caught: scan no longer clearing the product (1 check fails); an
    update_product that treats ids as file ids (3 checks fail on the offset copy). The file
    ids are refused only on the offset copy, as designed. A first defect, widening the
    lookup, was masked by the result keys and was not a real fault; it was dropped.
  - Real `reorganize` against the golden run: `golden_ops.py` on the new code, normal and
    `--prepare offset`, compared with `diff_runs.py` to `~/data/rpg_test_snapshots/golden`:
    IDENTICAL for all 15 states both times.
  - Note: the smoke state holds one never-scanned stray file, so a scan adds 3 files, not
    2; the script checks the two new files by path and every added file for an entry.
  - Left behind: `~/data/rpg_test_work` is in a post-run state; `restore_smoke.py` resets it.

### Phase 1b verification

Each step's tool is run against the existing snapshots where it can be, and its failure
modes are shown by an injected defect as in phase 1. Steps 9 to 11 were verified this way
on 2026-10-02 (see each step). Steps 12 to 14 were verified against the refactored code
on 2026-10-02.

## Phase 2: implement the refactor

Planned 2026-10-02 from a survey of `apps/rpg-librarian/src/rpg_librarian`. The user asked
to implement step 1 after seeing this plan, which accepts its stated defaults (below).

### Survey findings that shape the steps

- **Mixed table keys inside shared code.** `enrich` treats every source alike through
  `Source.table`, but `isbn_result` stays file-keyed while the other three evidence tables
  become entry-keyed. The same mix appears in `scan` (`_reset_judgment`,
  `_clear_scan_rows` call `session.get(table, file.id)` across both kinds) and in
  `report_file`. A wrong id there returns an empty or wrong row rather than failing; the
  offset-renumbered copy (step 8) is what exposes it.
- **Ids inside error text.** `reorganize` stores reasons such as "same destination as
  file(s) [3, 7]" in `error` rows; `update_product` and `rename_file` raise "file 12: no
  such file". The review-items agent reads these and calls the report tool with them, so
  they must be entry ids.
- **Raw SQL in the review-items skill** (`JOIN file f ON f.id = rf.file_id`,
  `f.product_id`) must be rewritten.
- **Not affected:** `observability` logging (`file_id` there is internal), `isbn_result`,
  `file_text`, the media tables, and the legacy `packages/rpg-librarian-mcp` (which has
  its own unrelated `Entry` model).

### Defaults accepted with the plan

- `Entry` follows the model convention (`EntityBase`: `created_at`, `updated_at`), seeded
  from the file's timestamps.
- Ids in tool output are named `entry_id`; no response contains a bare file id.
- The CLI verb `report-file` becomes `report-entry`, matching the tool.
- One `entries` helper turns ids into files and back, so the choice of id per table lives
  in one place.

Nothing is guaranteed to run between steps 1 and 3; work stays uncommitted on the branch
and the user chooses when to commit.

### Steps

- [x] **1. Model and migration `0005`.** `Entry(id, type, file_id UNIQUE, product_id)`
  with an index on `product_id` and cascade from `file`; `EntryType`; `EntryMetadataBase`
  in `core.py`; `EvidenceBase`, `FileTextAnalysis`, `Error`, and `ReviewFlag` re-keyed;
  `File.product_id` and its CHECK removed. Alembic migration seeding `entry.id = file.id`,
  copying every `product_id`, renaming the open-flag index, with a working downgrade.
  Verify: `scripts/check_migrations.py` passes; the real migration run on copies of both
  snapshots compares EQUIVALENT; its schema matches `simulate_migration.py` table by table;
  upgrade then downgrade round-trips.

  Done 2026-10-02.
  - **Model:** `model/EntryType.py`; `model/Entry.py` (`EntityBase`; `type`; `file_id` with
    `ON DELETE CASCADE` and `uq_entry_file_id`; indexed `product_id`); in `core.py`
    `EntryTypeType`, `EntryMetadataBase`, `EvidenceFields`, `EvidenceBase`, and
    `FileEvidenceBase`; `FileTextAnalysis` on `EntryMetadataBase`; `Error` and `ReviewFlag`
    on `entry_id` (index `ix_review_flag_open_entry_id`); `File` without `product_id` and
    its CHECK (a comment says `update_product` enforces the rule); exports in
    `model/__init__.py`.
  - **Deviation:** `IsbnResult` shares `EvidenceBase`, so the agreed wording "EvidenceBase
    extends EntryMetadataBase" would have re-keyed `isbn_result` too, against the agreed
    decision that ISBN evidence stays file-keyed. The evidence columns moved to an
    `EvidenceFields` mixin, with `EvidenceBase` (entry-keyed: DriveThruRPG, RPGGeek,
    Google) and `FileEvidenceBase` (file-keyed: ISBN only). Column order is unchanged.
  - **Migration:** `alembic/migrations/versions/0005_add_entry_table.py`. It creates and
    seeds `entry` (`id = file.id`, timestamps from the file, every `product_id`), rebuilds
    the six tables onto `entry_id` mapping each row through `entry.file_id` (not by
    assuming equal ids), rebuilds `file` without `product_id`, and refuses to run if
    `PRAGMA foreign_keys` is on (dropping a table would then cascade). The downgrade
    reverses it, mapping back through `entry`.
  - **Verified:**
    - `ruff check`, `ruff format --check`, and `scripts/check_migrations.py` pass: a fresh
      database built from the migrations matches the models.
    - The real migration on copies of both snapshots (via the new tool
      `migrate_copy.py`): integrity and foreign-key checks clean; about 1 second for the
      full catalog; `compare_catalogs.py` EQUIVALENT, with the structure check enabled.
    - Schema versus `simulate_migration.py` (new tool `schema_diff.py`): identical apart
      from the two intended differences, `entry`'s timestamps (an accepted default) and
      the renamed open-flag index.
    - Round trip: upgrade then downgrade to `0004` restores the original schema (including
      the CHECK) and every row of all 21 tables exactly (new tool `rows_equal.py`), on both
      snapshots.
    - Offset ids: the real migration renumbered by `renumber_entries.py` compares
      EQUIVALENT with 0 entry ids equal to file ids, and downgrading that copy also restores
      every row exactly, which proves the migration never relies on `entry.id = file.id`.
    - The live catalog and both snapshot catalogs still match their recorded hashes.
  - **Not verified:** the `foreign_keys` guard's refusal path (Alembic's connection always
    has enforcement off, so it was not triggered). The application code does not run yet:
    services still use `File.product_id` and `file_id` until steps 2 and 3, so `ty` was not
    run.
  - **Hazard until step 3 is done:** any CLI command or a restart of `rpg-librarian serve`
    from this checkout would migrate the catalog it opens to `0005` and then fail. The
    running server (started Oct 1) has the old code loaded and is unaffected until
    restarted. Do not run `process-batch.zsh` or restart the server from this checkout
    until the refactor is complete.

- [x] **2. Write paths: `scan`, `enrich`, errors.** Scan creates an entry with every file;
  the content-change reset clears `entry.product_id`; the `session.get` calls use the right
  id per table; `FileContext` gains `entry_id` and `enrich` keys each source's row
  correctly; `error_rows` take an entry id. Verify: golden steps 10 and 11, and a small
  `enrich --limit` on the smoke copy.

  Done 2026-10-02.
  - **`entries.py`** (new, package level): `keyed_by_entry(table)`, `row_key(table,
    file_id=, entry_id=)` (the one place that decides which id a per-item table uses),
    `file_entry`, `file_entry_id`, and `ensure_file_entry`. Step 3 adds the entry-to-file
    direction.
  - **`error_rows.py`** takes an entry id.
  - **`scan`**: every new file row gets its entry right after its first flush (both the
    normal path and the inspection-error path); scan-stage errors are written and cleared
    on the entry; the "retry files with scan errors" check joins `error` to `entry`; the
    content-change reset clears `entry.product_id` and deletes evidence through `row_key`
    (ISBN by file id, the rest by entry id); `_clear_scan_rows` also uses `row_key`
    (text analysis is entry-keyed, the scan tables file-keyed). The reset now runs after
    the flush that guarantees the entry exists; nothing between depends on the order.
  - **`enrich`**: `FileContext.entry_id`; eligibility joins `entry` and checks coverage
    on the table's own key (`issubclass(table, EntryMetadataBase)`); rows are keyed by
    entry or (ISBN) by file; errors by entry; `_has_results` checks `EvidenceFields`. The
    `Source` protocol and each source's `fetch` return their own table type.
  - **Static checks:** `ruff check` and `ruff format` clean; `ty` reports no errors in the
    changed files. The remaining `ty` errors are all in step 3's files (`services/*`,
    `paths.py`). `reorganize` still passes a file id to `record_error`: both are ints, so
    `ty` cannot see it; step 3 fixes it.
  - **Verified (old-code worktree `~/data/rpg_old_code` at `bf88dc3`, created for this):**
    - `golden_ops.py` gained `--steps` (run a subset), `--prepare offset` (migrate and
      renumber the catalog first), and two operations: `13-scan-corrupt-new` (a zero-byte
      PDF arriving, so a scan error lands on a brand-new entry; a truncated PDF was tried
      first, but PyMuPDF repaired it and no error was recorded) and `14-rescan-errored`
      (the retry path).
    - Steps 10, 11, 13, and 14 run on the old code, the new code, and the new code with
      offset entry ids: all three IDENTICAL. Covered: new files get entries, an automatic
      duplicate, the content-change reset (product link cleared, Google and text-analysis
      rows deleted), a scan error on a new entry, and its retry. The new code's first
      `scan` also exercised the automatic migration to `0005`.
    - `enrich --limit 1` (all five sources, real calls) on the normal and on the offset
      catalog: every new row (Google, DriveThruRPG, RPGGeek, text analysis, and the
      file-keyed ISBN row) belongs to the intended file, with no orphans and no foreign
      key problems; 0 of 70 entry ids equal their file id in the offset run.
    - `catalog_state.py` no longer records which schema it read and skips the `entry`
      table (it maps ids; its product links are reported per file). This made it truly
      schema-independent; the first comparison had failed only on those two artifacts.
    - The frozen golden run was regenerated from the old-code worktree with 15 steps; its
      13 earlier steps were identical to the previous golden run, apart from the removed
      schema marker.
    - The working tree is restored to the snapshot; the live catalog is unchanged.
  - **Not covered by step 2's checks:** `update_product`, reports, lists, `rename_file`,
    and `reorganize`, which are step 3. The hazard noted under step 1 still applies.

- [x] **3. Services and tools.** `update_product(entry_ids)` and its messages;
  `report_file` to `report_entry`; `list_unfiled` and `report_product` return entry ids;
  `rename_file(entry_id)`; `placement`, `paths`, `lists` read `product_id` through `entry`;
  `reorganize` carries `entry_id` in its placements so error text and printed lines use
  entry ids; CLI verbs follow. Verify: golden steps 02 to 09 and 12.

  Done 2026-10-02.
  - **`entries.py`** gained the entry-to-file direction: `entries_with_files` and
    `file_entry_ids`.
  - **`placement`**: reads each file with its entry; kept counts, groups, and subpaths use
    `entry.product_id`; `Placement` gained `entry_id` (`file_id` stays, for moving the row).
    **`paths.kept_file_count`** joins `entry`.
  - **`reorganize`**: blocked files, collision reasons ("same destination as entry(ies)
    [...]"), error rows, and printed lines ("blocked: entry 63") use entry ids; moving still
    loads the file row.
  - **`update_product`**: `UpdateProductRequest.entry_ids`, `MAX_ENTRIES_PER_CALL`; loads
    entries with their files, rejects unknown ids ("entry 63: no such entry"), non-file
    entries, duplicates (naming the original by entry id), and missing files; the product
    link is set on the entry and the disposition on the file; flags open and resolve on
    the entry; result key `updated_entry_ids`.
  - **`reports`**: `report_file` became `report_entry(entry_id)`, returning `entry: {id,
    type}`, `file` without an id, `duplicate_of.entry_id`, `duplicate_entry_ids`, and
    evidence through `row_key`; `report_product` lists `entry_id` per file; `report_line`
    counts through `entry`. **`lists`**: the worklist joins `entry`, returns `entry_id`,
    and checks flags and text analysis by entry; type counts join `entry`.
  - **`rename_file(entry_id)`**: rejects unknown and non-file entries; messages and the
    result name entry ids; the subpath clash check finds the product's files through
    `entry`.
  - **Wiring:** MCP tools `report_entry`, `update_product(entry_ids)`,
    `rename-file(entry_id)`, with their docstrings updated for the new parameters; CLI verb
    `report-entry` and `update-product ENTRY_IDS`.
  - **Static checks:** `ruff check`, `ruff format --check`, `ty check` (no errors anywhere),
    and `scripts/check_migrations.py` pass.
  - **Verified:**
    - The full 15-step golden run on the new code, normal and with offset entry ids, is
      IDENTICAL to the frozen run of the old code in every step: catalog contents and
      files on disk after each `reorganize`, `update_product`, `rename_file`, and `scan`.
    - Command output differs from the old code's only by the intended renames
      (`file` to `entry` in blocked lines, `updated_entry_ids`, `entry_id`); in the offset
      run every id shown is an entry id (100063, 100067, 100016), never a file id.
    - On the offset catalog: a file id passed to `update-product` or `report-entry` is
      refused ("entry 63: no such entry"); an automatic duplicate is refused naming its
      original by entry id; `report-entry`, `list-unfiled`, and `report-product` return
      entry ids only.
    - A copy of the full snapshot, run through `guarded_run`, was migrated automatically by
      the new CLI; `reorganize --dry-run` gives the same plan as the snapshot (0 to move,
      34,243 in place), `compare_catalogs.py` is EQUIVALENT, and the worklist count agrees.
    - The working tree is restored; the live catalog is unchanged.
  - **For phase 1b steps 12 and 13:** `snapshot_placements.py` must also drop `entry_id`
    (it drops `file_id` and `root_id`); `snapshot_reports.py` must call `report_entry`; the
    report comparison must allow `file.id` to disappear and `entry`, `duplicate_of.entry_id`,
    `duplicate_entry_ids`, and `entry_id` in lists to appear.
  - **Hazard update:** the code now runs end to end, so the step 1 warning changes: any
    command or server restart from this checkout migrates the catalog it opens to `0005`
    and works. Do not point it at the live catalog until phase 3 is done and a backup is
    taken.

- [x] **4. Text surfaces.** Tool docstrings, server instructions, `describe_schema` notes,
  the `process-batch` and `review-items` skills including their SQL, and `design-assets` in
  the seed types. Verify: a grep audit that every remaining `file_id` and `product_id` is
  intentional.
  - Done 2026-10-02. Server `INSTRUCTIONS` name `report_entry` and say every item id is an
    entry id. `describe_schema` gains an `entry` note, says which tables are keyed by
    `entry_id` and which by `file_id`, and its three example queries join through `entry`
    and return `entry_id`. Both skills say `report_entry` and "entry ID"; their SQL joins
    `review_flag`/`error` to `entry` and `entry` to `file`, returns `en.id AS item_id` and
    `en.product_id`, and paginates on `en.id`. `review-items` documents the new
    `same destination as entry(ies)` message and that older `file(s)` rows carry the same
    ids. `design-assets` appended to `SEED_PRODUCT_TYPES` (the live catalog has it as id 12).
    Tool docstrings were already updated in step 3.
  - Verified: `~/data/rpg_test_tools/check_skill_sql.py` runs every skill and schema
    example query, old text on the pre-migration catalog and new text on the migrated
    copy, and compares the non-id columns (including `product_id`): SAME for all six
    queries on the smoke copy (10 flags, 1 blocked, 1 occupant, 3 errors), the offset copy,
    and the full copy (2 needing analysis, 3 errors); every returned `item_id`/`entry_id`
    is an entry whose file has the returned path (ids above 100000 on the offset copy).
    `describe_schema` on the offset copy shows the `entry` note; `init` on a fresh `/tmp`
    catalog seeds all 11 types including `design-assets` and installs the new skills.
    Grep audit: remaining `file_id` uses are joins to `entry`, file-keyed tables (ISBN,
    text, metadata, media), internal placement/move bookkeeping, and local log fields;
    remaining `report_file`/"file id" text is only in migrations and a docstring that says
    file ids never leave the catalog. ruff, ruff format, ty, and the migrations check pass.
  - **Cutover note:** `init` never overwrites installed skills, and
    `~/data/rpg-librarian/.claude/skills/process-batch/SKILL.md` is a locally edited older
    copy (its `review-items` matches HEAD). At cutover, replace the installed
    `review-items` with the new one and port the entry-id changes into the edited
    `process-batch` by hand (or replace it, if the local edits are not wanted).
- [x] **5. Static checks.** `ruff`, `ty`, and the alembic check.
  - Done 2026-10-02: `ruff check`, `ruff format --check` (90 files), `ty check`, and
    `scripts/check_migrations.py` (upgrade to head, then "Migrations match the SQLModel
    schema") all pass on the whole app.

## Phase 3: verification

Finish phase 1b steps 12 to 14, then run them: snapshot scripts for the new names, the
report comparison, the scripted tool-level checks on the normal and offset copies, the
golden comparison with the new code, and the full snapshot run through `guarded_run`.

- [x] Phase 1b steps 12 to 14 done (see above), including the golden comparison with the
  new code (IDENTICAL, normal and offset).
- [x] **Full snapshot run, 2026-10-02.** On a pristine copy of `full/catalog.db` (alembic
  `0004`, 34,293 files), through `guarded_run.py`, which refused the live catalog (exit 2):
  - **Cutover path:** the first command on the copy (`list-types`) migrated it to `0005` in
    2.6 s; 34,293 entries for 34,293 files, integrity ok, no foreign key problems.
  - **`reorganize --dry-run`:** identical to the saved `full/dry-run.txt` (0 to move, 0
    blocked, 34,243 in place).
  - **Normal and offset-renumbered copies (+100000, 0 entry ids equal to their file ids):**
    `snapshot_placements.py` is byte-identical to `full/placements.json` (34,243);
    `compare_catalogs.py` with placements: EQUIVALENT; `compare_reports.py` on the sampled
    reports (131 files, 28 products, 28 lines): EQUIVALENT, 192 documents, 0 differences;
    the six skill/schema queries (`check_skill_sql.py`): SAME.
  - **CLI on the offset copy:** `report-entry` and `update-product` refuse a file id
    (`No entry with id 8565`; `entry 1: no such entry`), leaving the row unchanged; the same
    call with the entry id works (unfiling entry 100001 clears its product, and
    `list-unfiled --folder games --recursive` then returns it as `entry_id` 100001, with no
    `id` or `file_id`). The unfile was on a throwaway copy.
  - **Live catalog:** hash `0bd57afa...` unchanged throughout (guard and manual check).
  - The full catalog has no present unfiled files, so its worklist is empty (1 only after
    the test unfile); the unfiled listing is therefore exercised by the smoke checks.
- [x] **Cutover, 2026-10-02 (user approved).**
  - Backups in `~/data/rpg-librarian/backups/`: `catalog.pre-entry-table.rawcopy.db` (a
    byte copy, SHA-256 `0bd57afa...`, equal to the live file before migrating) and
    `catalog.pre-entry-table.db` (SQLite backup API; integrity ok, `0004`, 34,293 files).
    Also `process-batch.SKILL.md.pre-entry-table` (the locally edited skill) and
    `review-items.SKILL.md.pre-entry-table`.
  - Migrated the live catalog to `0005` by running `list-types` with the new code (1.6 s):
    integrity ok, 0 foreign key problems, 34,293 files and 34,293 entries (ids equal to
    file ids), `file` has no `product_id`. Against the byte copy: `compare_catalogs.py`
    with placements EQUIVALENT, placements byte-identical (34,243), the six skill/schema
    queries SAME.
  - Installed skills replaced with the bundled versions (user chose to replace rather than
    merge `process-batch`; `review-items` replaced too, as it matched the old bundled
    copy). Only `.claude/skills/` exists in the library project. No `report_file` or
    "file ID" remains in either.
- [x] **Finish, 2026-10-02.** The user killed the old `rpg-librarian serve` (PID 198205). A
  new server built from this checkout (`create_server`, run in-process against the live
  catalog with read-only calls) lists the ten tools including `report_entry`, answers
  `list_product_types`, `report_entry(1)`, and a `query`, and leaves the catalog's hash
  unchanged. The `~/data/rpg_old_code` worktree was removed (`git worktree remove --force`;
  the frozen golden run and snapshots stay in `~/data/rpg_test_snapshots/`). Ruff, ruff
  format, ty, and the migrations check pass. Committed on branch `tooling-refactor` (not
  pushed).
