# Pack migration: progress

Implementation started 2026-10-03 on the user's request: phases 1 to 4, then stop
before the live migration so the user and the agent hand-check the migrated copy.

## Where things are

| Location | What |
|---|---|
| `~/data/rpg-librarian/backups/catalog.pre-pack-migration.rawcopy.db` | raw `cp` of live, sha256 `3e73f6af…` (= live), read-only |
| `~/data/rpg-librarian/backups/catalog.pre-pack-migration.db` | SQLite backup API copy, sha256 `3b975b1c…`, read-only |
| `~/data/rpg_test_snapshots/pack-migration/baseline/` | immutable baseline: `catalog-0005.db`, 0005-code captures, `MANIFEST.md` |
| `~/data/rpg_test_snapshots/pack-migration/live.sha256` | live hash for `guarded_run.py --live-sha-file` |
| `~/proj/rpg-librarian-mcp-0005` | detached `git worktree` of `5c8b268` (the 0005 code), for baseline captures |

## Phase 1: done (2026-10-03)

- No process had the live catalog open (`fuser` empty). A Claude session (pid 198136)
  has `~/data/rpg-librarian` as its working directory, open since 2026-10-01, with no
  `rpg-librarian serve` process running. If its MCP server restarts it would upgrade the
  live catalog with the working-tree code; left alone, flagged to the user.
- Backups made, hashed, `integrity_check` ok, `foreign_key_check` empty, both at `0005`,
  `rows_equal.py` identical, then `chmod 444`. Live hash unchanged across the copy.
- Baseline captured on a copy of the backup with the 0005 code (`--project` the
  worktree): placements (34,252), sampled reports (131 files, 28 products, 28 lines),
  `reorganize --dry-run` (0 to move, 0 blocked, 34,252 in place), `list-unfiled` (0),
  `list-types`. Copy hash and revision unchanged afterward. Details in the baseline
  `MANIFEST.md`.
- `guarded_run.py`'s default live hash (`full/live.sha256`) is stale (`0bd57…`, from
  before entry-table); this work passes `--live-sha-file` with the current hash instead
  of overwriting the old snapshot.
- Gotcha hit: zsh does not word-split a command held in a string variable; use an array.

## Phase 2: done (2026-10-03)

`~/data/rpg_test_tools/pack_migration_validate.py ORIGINAL MIGRATED [--list L]
[--placements-before B --placements-after A] [--json OUT]`: plain `sqlite3`, both
databases read-only (`ATTACH`), no `rpg_librarian` import. No `--list` means the
schema-only checkpoint. Checkpoints: `schema` (revisions, integrity, foreign keys,
tables, columns, indexes, foreign keys, the entry CHECK), `list vs original` (each
listed member as listed, filed, not a duplicate, below its folder, no open flag or
error, and every eligible file below the folder listed), `preservation` (every
original table diffed by primary key with `EXCEPT`; differences permitted only per
record and field, below), `completion` (every listed pack, exact members, product,
disposition, linked `folder_judgment`, pack search; no unapproved pack, judgment, or
`folder_search` row), `invariants`, `effective decisions` (every file's disposition and
product, through its pack for members), `placements` (all fields but `pack_id`). It
prints the deleted entry-keyed rows per table, so the evidence loss is always visible.

Permitted differences: a member's `file` row may change only `disposition` (to
`unfiled`) and `updated_at`; its `entry` must be gone, with exactly the rows keyed to
it; each pack adds one pack entry, one `folder_judgment` row (`pack`, linked), and a
`google_search_result` row equal to the list's search. Nothing else.

Demonstrated with `pack_migration_demo.py` (damages throwaway copies; each must fail
naming the expected checkpoint):
- schema-only, on the real `0006` upgrade of the baseline: clean PASS; 10/10 damaged
  cases rejected (lost file, changed disposition, changed product, unrelated evidence
  lost, evidence value changed, review flag changed, product renamed, unexpected pack,
  stray search cache, index dropped).
- adoption cases: run on the fixture in phase 3 (13/13 rejected, 1 skipped there because
  the fixture list has no searches) and again on the rehearsal in phase 4.

## Phase 3: done (2026-10-03)

- `apps/rpg-librarian/src/rpg_librarian/find_packs/adopt.py`: `Adopter`, a subclass of
  `find-packs`'s `Finder` (normal `find-packs` code is untouched), plus `propose`,
  `check_source`, and `apply_plan`.
- `scripts/migrate_packs.py`: `upgrade` / `propose` / `apply [--check-only]`, separate
  steps. `propose` never runs on live; `upgrade` and `apply` need `--live` for it.
  `apply` opens without migrating, needs `0006`, refuses an incomplete list, and is all
  or nothing; an exactly applied list is a no-op.
- Adopt mode: walks each line folder's child folders; a candidate is a kept product's
  own folder (placement's own path rule) whose eligible files are all `keep` for that
  product, with no kept present file of the product elsewhere and no open flag or
  error; then the existing gate, search, model, and lossless `_form` (dry run). Container
  and no-pack answers are stored, not descended into. The list holds per pack: root,
  folder, fingerprint, product (id and names), disposition, reason, evidence, search
  results, and per member: file and entry ids, path, size, mtime, sha256, media type,
  disposition, subpath.
- Source match on apply: root, product names, folder fingerprint, exact eligible
  members, each member's path/size/mtime/sha256/disposition/subpath/entry, still filed
  to the product, no kept file of it elsewhere, no kept pack of it, no open flag or
  error, folder still the product's own.

**Deviation from checks.md (and why):** a member keeps its stored `subpath` instead of
having it cleared. `membership.join` clears it, and placement then derives a member's
path relative to the deepest folder holding all members, so a product whose files all
sit in one subfolder would get new destinations. Every live kept file has a stored
subpath, and placement uses a stored subpath for members first, so restoring it makes
every destination identical by construction. A stored member subpath is a normal state
(`reorganize` stores them). The validator requires each member's subpath unchanged.

Missing files are never members (as in `find-packs`): a missing kept file in an adopted
folder stays loose with its own entry and decision. The live catalog has no missing
kept files.

Fixture checks, `~/data/rpg_test_tools/pack_adopt_checks.py` (offline, stub model, no
search, on `smoke-packs` plus set-up cases): 34/34 passed. Covered: the two uniform asset
folders proposed and nothing else; a scanned automatic duplicate excluded; mixed,
flagged, kept-elsewhere, and document folders not candidates; a `no_packs` answer not
proposed; a second propose asks nothing and lists the same packs; `--check-only` writes
nothing; apply forms 2 packs/29 members; the independent validator passes (with
placements from the 0005 code on a 0005 copy vs the new code); reapply is a no-op;
`reorganize --dry-run` and `list-unfiled` unchanged; `report-pack` correct; refusals
(existing pack, changed source, incomplete list, live catalog for all three steps) with
the catalog unchanged; the missing file stays loose; adoption damage cases 13/13.

Regression and static checks: `pack_dissolve_checks.py` 11/11 (normal `find-packs`
path), `ruff check`, `ruff format --check`, `ty check` clean on the new files,
`scripts/check_migrations.py` reports the migrations match the models.

## Phase 4: rehearsal (2026-10-03)

Files in `~/data/rpg_test_snapshots/pack-migration/rehearsal/`:

| File | What |
|---|---|
| `schema.db` (read-only) | backup → `migrate_packs.py upgrade`; sha256 `cd72b0a2…` |
| `proposal.db` | schema copy holding the stored model answers and searches (keep: a rerun asks nothing) |
| `list.json` (read-only) + `list.review.md` | **the reviewed adoption list for live**: 117 packs, 7,608 members |
| `applied.db` | schema copy with `list.json` applied: **the copy to hand-check** |
| `downgraded.db` | `applied.db` downgraded to 0005 (rollback rehearsal) |
| `validate-schema.json`, `validate-applied.json`, `demo-adoption.txt`, `app-checks.txt` | check outputs |

Results, in order:
1. Upgrade of a fresh backup copy (0.6 s). Schema-only validator: PASS (34,302 files,
   every original row and value unchanged). Placements byte-identical to the 0005
   baseline after the upgrade alone.
2. Load measured offline first (stub model, no search, scratch copy): 2,680 candidate
   product folders, 2,486 dropped by the gate, 1 skipped for an error row
   (`games/GURPS/Transhuman Space - Teralogos News`, a PDF folder), 194 to ask in 77
   calls. Then a 2-call trial (model and Serper both working), then the full proposal:
   **77 model calls, 192 searches made (2 generic names skipped), 0 errors**; answers:
   117 pack, 74 no_packs, 3 container (`Dungeons on Demand` volumes), 0 mixed.
   Proposed by type: handout-art 37, games 25, vtt packs 19, maps 18, soundtracks 12,
   design-assets 3, system-agnostic-text 2, miniatures 1.
3. `apply --check-only` then `apply` on a fresh schema copy: 117 packs, 7,608 members,
   5 s. Independent validator with placements: **PASS**. Deleted with adopted entries:
   entry 7,608, google 7,608, dtrpg 47, rpggeek 47, text analysis 47, review flags 42
   (all resolved), errors 0. 34,252 placements identical to the 0005 baseline.
4. Adoption damage cases on the rehearsal result: clean PASS, **14/14 rejected**.
5. Reapply on a copy: "Already applied", file byte-identical.
6. Downgrade of a copy of `applied.db` to 0005: integrity ok, foreign keys clean, every
   file's disposition, product, and subpath identical to the baseline, placements (0005
   code) identical; evidence not restored (google 33,491 → 25,883, dtrpg/rpggeek/text
   analysis −47, review flags 492 → 450). So the backup is the complete rollback.
7. Backup restore: `cp` of `catalog.pre-pack-migration.rawcopy.db` hashes `3e73f6af…`
   (= live before), rows identical to the baseline, integrity ok, revision 0005.
8. Application checks (`pack_migration_app_checks.py`, new code, read-only, both
   catalogs' hashes unchanged): **8/8 passed**. `reorganize --dry-run` exactly the
   baseline's plan (0 to move, 0 blocked, 34,252 in place); `list-unfiled` unchanged;
   `list-types` unchanged; all 117 `report-pack`s match the list; each adopted
   product's `report-product` shows its pack; every other sampled report (131 entries,
   28 products, 28 lines; 25 sampled entries were adopted) identical between the
   schema-only and adopted copies. First run failed 2 checks on the presentation
   differences below; the checks were then made precise to permit exactly those.

Expected presentation differences found by the application checks (not data changes):
- `list-unfiled` gains the key `total_unfiled_packs` (0) in the new code.
- 55 automatic duplicates have an original that became a pack member. Their
  `report-entry` shows `duplicate_of.entry_id: null` (the member has no entry of its
  own; path and `duplicate_of_id` unchanged). This is how the existing pack-support
  report code presents a duplicate of a member; it may deserve a follow-up (show the
  pack's entry), outside this item.
- Reports of the adopted products list the pack under `packs` instead of their files.

## Phase 5 runbook (not run; for the live cutover after the joint hand checks)

Variables (zsh):

```zsh
LIVE=~/data/rpg-librarian/catalog.db
BK=~/data/rpg-librarian/backups
PM=~/data/rpg_test_snapshots/pack-migration
T=~/data/rpg_test_tools
NEW=~/proj/rpg-librarian-mcp/apps/rpg-librarian
MIG=(uv run --quiet --project $NEW python ~/proj/rpg-librarian-mcp/scripts/migrate_packs.py)
```

1. **Quiet the catalog.** Close the Claude session whose working directory is
   `~/data/rpg-librarian` (pid 198136 on 2026-10-03), and run nothing else there
   (`process-batch.zsh`, `rpg-librarian` commands). Check `fuser $LIVE` prints nothing.
2. **Confirm the live catalog is the rehearsed baseline.**
   `sha256sum $LIVE` must equal `3e73f6afed0fe1100d29490e325dc512e067269a57803725d77629d14d58c5f8`
   (`$PM/live.sha256`). If it differs, stop: refresh the backups and baseline (phase 1),
   then repeat the rehearsal (phase 4), because the list's source-match may no longer
   hold and the validator's original would be stale.
3. **Upgrade.** `$MIG upgrade --catalog $LIVE --live` → `0005 -> 0006`.
4. **Schema-only checkpoint.**
   `python3 $T/pack_migration_validate.py $BK/catalog.pre-pack-migration.db $LIVE`
   → `PASS`. On failure: restore (step 9).
5. **Source match.** `$MIG apply --catalog $LIVE --list $PM/rehearsal/list.json --check-only --live`
   → `ready: 117 ... problems: 0`. On any problem: stop; the catalog is only upgraded,
   which is safe to leave or restore.
6. **Apply.** `$MIG apply --catalog $LIVE --list $PM/rehearsal/list.json --live`
   → `Applied: 117 pack(s), 7608 member file(s)`.
7. **Validate.**
   `uv run --quiet --project $NEW python $T/snapshot_placements.py $LIVE $PM/live-placements-after.json`, then
   `python3 $T/pack_migration_validate.py $BK/catalog.pre-pack-migration.db $LIVE --list $PM/rehearsal/list.json --placements-before $PM/baseline/placements.json --placements-after $PM/live-placements-after.json --json $PM/live-validate.json`
   → `PASS` with the same deleted-row counts as the rehearsal (entry 7608,
   google 7608, dtrpg 47, rpggeek 47, text analysis 47, review flags 42, errors 0).
8. **Application checks (live, read-only verbs, plain CLI since `guarded_run` refuses live):**
   `rpg-librarian reorganize --dry-run --catalog $LIVE` must print exactly
   `$PM/baseline/reorganize-dry-run.txt` (0 to move, 0 blocked, 34252 in place);
   `rpg-librarian list-unfiled --recursive --include-flagged --limit 100000 --catalog $LIVE`
   must equal `$PM/baseline/list-unfiled.json`. Spot-check a few `report-pack` entries.
9. **Rollback, if any check fails:** `cp $BK/catalog.pre-pack-migration.rawcopy.db $LIVE`
   (then `chmod 644 $LIVE`), and confirm `sha256sum $LIVE` is `3e73f6af…`. Rehearsed:
   the restored copy is byte-identical and rows-identical to the baseline. A downgrade
   (`alembic` to `0005`) restores decisions and placements but not the deleted evidence,
   so restoring the backup is the complete rollback.
10. Record the outcome here and in `item.md`, then resume scan/enrich/filing.

## Hand checks (next, with the user) and changing the list

Hand-check on `rehearsal/handcheck.db` (a copy of `applied.db`, which is now read-only,
sha256 `9dd1d039…`). Its roots point at the real library (`/phinneas/rpg/...`): use only
read-only verbs (`report-*`, `list-*`, `reorganize --dry-run`), preferably through
`python3 ~/data/rpg_test_tools/guarded_run.py --catalog $PM/rehearsal/handcheck.db
--live-sha-file $PM/live.sha256 -- VERB ...`. Never `scan`, `enrich`, `reorganize`
without `--dry-run`, or the MCP server of the Claude session in `~/data/rpg-librarian`
(it opens the live catalog and would upgrade it).

Proposed agenda:
1. Packs whose member PDFs are books with their own identity (adoption deletes those
   PDFs' DTRPG/RPGGeek/text-analysis rows and they lose their own entry): most
   doubtful are `games/Dungeons & Dragons 5th Edition/Time & Time Again` (adventure),
   `games/Index Card RPG/Grizzly Encounter - Civilizations` and `- Monsters Vol 1`
   (supplements), `system-agnostic-text/Kozmik Objects & Entities/...` (book), and the
   Index Card RPG VTT folders `Xeno Dead Zone` (rulebook), `Witcher` (setting), `The
   Division` (setting), `The Turnip Knights`, `Relics of Odium`, `Shadows in the Dark`,
   `Bast Encounter Pack 1.0` (adventures), `Hero Cards`. Others carry only a notes,
   sleeve-notes, or license PDF, which a pack is meant to include.
2. The largest packs: Arc Dream `Digital Assets - International Pack 1 - Europe`
   (1,611), `Doskvol Locations - Tier 03 Print Maps` (565), `Dungeon Architect Cards`
   (333).
3. One adopted product's `report-product` and `report-pack`.
4. A duplicate of a member (55 exist), e.g. `report-entry 4121`.
5. The three `Dungeons on Demand` volumes (answered `container`, left loose).
6. `reorganize --dry-run`: 0 to move.

Optional before cutover (user's choice): a plain export of the 42 resolved review
flags' notes that adoption removes, written beside the backup.

**If the list is edited (for example, dropping doubtful packs), the rehearsal evidence
no longer describes it.** Re-validate, with no paid calls:
1. Write the edited list as a new file (e.g. `rehearsal/list-v2.json`), keeping
   `"complete": true`; never edit `list.json` in place.
2. `cp rehearsal/schema.db rehearsal/applied-v2.db; chmod 644 ...`, then `$MIG apply
   --catalog rehearsal/applied-v2.db --list rehearsal/list-v2.json`.
3. `snapshot_placements.py` (new code) on it, then `pack_migration_validate.py` with
   `--list` and placements, `pack_migration_app_checks.py --adopted ...applied-v2.db
   --list ...list-v2.json`, and `pack_migration_demo.py` with the same arguments.
4. Point the phase 5 runbook at `list-v2.json` and update the expected counts.

Housekeeping after the live cutover: remove the `~/proj/rpg-librarian-mcp-0005`
worktree (`git worktree remove`), and the ~3 GB of catalog copies under
`~/data/rpg_test_snapshots/pack-migration/` once no longer needed. Spend so far: 77
model calls and 192 searches in total (a 2-call trial plus the full run of 75 calls and
190 searches, which reused the trial's 2 answers).
After cutover, avoid `scan --force` over packs at first: a member that fails any scan
stage is taken out of its pack (asset-pack-support note), and some packs hold
`unknown`-type files (fonts, brushes).

## Phase 5: live cutover done (2026-10-03, on the user's go-ahead after hand checks)

Run exactly as the runbook above, with the unedited `rehearsal/list.json`:
1. Preconditions: `fuser` empty; no `rpg-librarian serve`/scan/enrich process. The old
   Claude session (pid 198136) in `~/data/rpg-librarian` was still alive but had no
   MCP server running. Live sha256 `3e73f6af…` = rehearsed baseline.
2. `upgrade --live`: `0005 -> 0006`. Schema-only validator vs
   `backups/catalog.pre-pack-migration.db`: **PASS** (34,302 files).
3. `apply --check-only --live`: 117 ready, 0 problems. `apply --live`: **117 packs,
   7,608 members**.
4. Validator with the list and placements (baseline 0005-code placements vs new-code
   placements of live): **PASS**; deleted rows identical to the rehearsal (entry 7,608,
   google 7,608, dtrpg 47, rpggeek 47, text analysis 47, review flags 42 resolved,
   errors 0); 34,252 placements identical. Report: `pack-migration/live-validate.json`.
5. Application checks on live (read-only verbs; hash unchanged across them):
   `reorganize --dry-run` byte-identical to the baseline (0 to move, 0 blocked, 34,252 in
   place); `list-unfiled` equal to the baseline (`total_unfiled_packs` 0);
   `report-pack 34318` correct. Revision `0006`, integrity ok, 117 packs.
6. Live sha256 after the migration: `f91200663917919ec9ad346d1725d7cf371431e4fe6a9c100f685231a50adfa0`.

Rollback, if ever needed: `cp ~/data/rpg-librarian/backups/catalog.pre-pack-migration.rawcopy.db
~/data/rpg-librarian/catalog.db && chmod 644 ~/data/rpg-librarian/catalog.db` (restores
`3e73f6af…`; any work done after the cutover would be lost).

Not done (left to the user): commits; removing the `~/proj/rpg-librarian-mcp-0005`
worktree and the ~3 GB of copies under `~/data/rpg_test_snapshots/pack-migration/`;
the optional export of the 42 resolved review-flag notes (still recoverable from the
backup); the follow-up for `duplicate_of.entry_id: null` on the 55 duplicates of
members. Avoid a first `scan --force` over packs (see the hand-check section).

## After cutover: pipeline readiness (2026-10-03)

- `process-batch.zsh` (live `~/data/rpg-librarian/` and repo `scripts/`) now runs
  `rpg-librarian find-packs --root /phinneas/rpg/inbox` between `scan` and `enrich`;
  without it no pack forms, and filed folders are never judged later. Old live script:
  `backups/process-batch.zsh.pre-find-packs`.
- The live project's skills (`~/data/rpg-librarian/.claude/skills/`) were the
  entry-table versions with no pack support (`init` never overwrites local copies).
  Replaced both `SKILL.md` files with the bundled ones; old copies in
  `backups/claude-skills.pre-pack-support/`.
- Still for the user: restart the Claude session in `~/data/rpg-librarian` (it loaded the
  old skills), commit, and run the first real dump with `find-packs --dry-run` first.
