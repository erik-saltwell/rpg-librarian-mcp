# Asset pack support: plan

Written 2026-10-02. Nothing here is built yet. The design is in [intent.md](intent.md)
(current) and [idea.md](idea.md) (background). This plan does not repeat them; it
records what the code requires, the decisions the design left open, and the phases.

**In one paragraph.** Add `pack` as a second entry type. A pack owns its product and
disposition; its member files have `file.pack_id` set and no entry of their own. A new
`find-packs` command forms packs from catalog folder evidence, a cached folder-name
Google search, and a top-down LLM classification. `create-pack`, `add-to-pack`,
`remove-from-pack`, and `report-pack` let a person or the agent correct and inspect
packs. Every reader of entries, placement, and enrichment learns about packs, and the
`process-batch` and `review-items` skills follow.

## Ground rules

- **Never touch the live catalog in this item.** `db.session_scope()` migrates to head by
  default, so *any* CLI verb run with the new code upgrades the catalog it opens, and
  `serve` migrates at startup. Every check here runs on `~/data/rpg_test_work` (rebuilt
  from `~/data/rpg_test`) or on a *copy* of `~/data/rpg-librarian/catalog.db`. Until
  [pack-migration](../pack-migration/item.md) runs, do not restart an MCP client whose
  server points at the live catalog with this code checked out.
- **Precondition:** the working tree has the user's uncommitted `clear_errors` work
  (`services/clear_errors.py`, edits to `server/tools.py`, `commands/tools.py`,
  `__main__.py`, `README.md`). It should be committed (by the user) before phase 1 starts,
  so this item's diffs stay separate. This plan does not touch it.
- **Verification policy:** no new unit tests and no test tooling in the repo. Checks are
  `ruff check`, `ruff format --check`, `ty check`, `scripts/check_migrations.py`, direct
  CLI and MCP runs, and the existing out-of-repo scripts in `~/data/rpg_test_tools/`
  (`build_smoke.py`, `add_fixtures.py`, `golden_ops.py`, `diff_runs.py`,
  `catalog_state.py`, `tool_checks.py`, `migrate_copy.py`, `compare_catalogs.py`).
  Commands are run from the repo root as
  `uv run --project apps/rpg-librarian rpg-librarian <verb> … --catalog <path>`.
  The commands below are planned, not yet run.

## Code inspected (2026-10-02)

Under `apps/rpg-librarian/src/rpg_librarian/`:

| Area | Files | What packs change |
|---|---|---|
| Model | `model/Entry.py`, `model/File.py`, `model/core.py`, `model/EntryType.py`, `model/Disposition.py`, `entries.py` | New `Pack` model and table; `EntryType.pack`; `entry.pack_id`; `file.pack_id`; entry helpers that today assume every entry is a file. |
| Migrations | `alembic/migrations/versions/0005_add_entry_table.py` | `0006` follows its table-rebuild pattern (foreign keys off, `<table>_new`, copy, swap). |
| Scan | `commands/scan.py` | `_clear_errors`, `_clear_scan_rows`, `_reset_judgment`, `_record_error` call `file_entry`/`file_entry_id`, which raise `LookupError` for a file with no entry; `_join_duplicates` can demote an `unfiled` row; new files need auto-join. |
| Placement | `services/placement.py`, `paths.py` (`kept_file_count`), `services/pending.py` | Every query joins `entry.file_id = file.id` and reads `file.disposition`; members would vanish from placement and pending counts, and a pack's product would count 0 kept files (members would go flat into the line folder). |
| Reorganize | `commands/reorganize.py` | `by_id`, `blocked`, and `_collisions` are keyed by `entry_id`; members share one entry and would overwrite each other. |
| Enrich | `commands/enrich.py`, `enrichment/{base,queries,dtrpg,rpggeek,google,isbn,text_analysis,registry}.py` | `_eligible` builds one `FileContext` per file entry; `FileTracker` takes a file id; dtrpg and rpggeek only want product documents; Google uses `pack_query`; text analysis takes one file's samples. |
| Services and tools | `services/{reports,lists,update_product,rename_file,schema}.py`, `server/tools.py`, `commands/tools.py`, `__main__.py` | `report_entry` rejects non-file entries; `list_unfiled`, `report_product` (`_files_summary`), `report_line`, `list_product_types` (kept counts) are file-only; `update_product._load_entries` refuses non-file entries; schema notes and examples join `en.file_id = f.id`. |
| Skills | `resources/skills/process-batch/SKILL.md`, `resources/skills/review-items/SKILL.md` | Worklist and SQL assume file entries; `review-items` SQL joins `file f ON f.id = en.file_id`. |

## Decisions made during planning

`intent.md` left these open, or the code forced them. The agent proposed each one, and
the user confirmed all ten on 2026-10-02. Decisions 3 and 7 were changed from the
original proposal; both changes are noted below.

1. **Tools address members by path, never by file id.** Members have no entry id and file
   ids never reach the LLM. `create-pack(root_id, folder, …)`,
   `add-to-pack(pack_entry_id, root_id, path)`, and
   `remove-from-pack(pack_entry_id, path)` take a root-relative file *or* folder path;
   `report-pack` shows those paths.
2. **Joining a pack normalizes the member.** On joining, the file's entry is deleted
   (cascading its evidence, text analysis, errors, and review flags), `file.pack_id` is
   set, and `file.disposition` is set to `unfiled` (ignored while a member, per intent,
   and errs toward "not kept" for any query that forgets `pack_id`). `file.subpath` is
   cleared. On leaving, the file gets a new file entry, `unfiled`, no product.
3. **Adding a filed loose file is allowed, and reported.** `add-to-pack` and
   `create-pack` accept a loose file filed to a different product or disposition than
   the pack's; the tool output lists every decision that was dropped (file, previous
   product, previous disposition). Automatic duplicates are still refused. This loosens
   only the manual tools; `find-packs` keeps lossless formation. (User's choice; the
   agent had proposed refusing such files.)
4. **Scan on members.** A member that is rescanned successfully stays in its pack; only
   its file-level rows are replaced, and entry-keyed steps are skipped. A changed member
   stays too (the pack's decision is about the pack, not one file's bytes); its pack's
   text analysis may go stale, which is accepted. A member whose scan *fails* is detached:
   it gets its file entry back (unfiled), and the error is recorded there, so it is
   visible and retried like any other failure.
5. **Members are never demoted to duplicates.** `_join_duplicates` treats pack
   membership like an LLM decision: a member is never made a duplicate. A loose copy of a
   member's content can still become a duplicate of it.
6. **A pack row cannot lose its members silently.** `file.pack_id` is
   `ON DELETE RESTRICT`; services delete a pack only when it has no members, in the same
   transaction that removed the last one (intent: empty packs are deleted).
7. **At most one *kept* pack per product, enforced in the services.** `update_product`,
   `create-pack`, and `add-to-pack` refuse to give a product a second pack with
   disposition `keep`, with a readable `UsageError` naming the other pack and the merge
   tool. There is no database index: the disposition lives on `pack`, which an index on
   `entry` cannot see, and a superseded earlier version of a pack may legitimately share
   its product with the kept one (superseded packs go to `.trash/`, so they cannot
   collide). This replaces the agent's first proposal of a partial unique index, which
   would have forbidden that case. It narrows intent's "a product has at most one pack"
   to kept packs.
8. **Reorganize errors for members land on the pack entry.** Internally `reorganize`
   keys placements by file id. A blocked or failed member records one `reorganize` error
   on the pack's entry, summarizing how many members failed and the first few reasons;
   command output still lists each file.
9. **Where `find-packs` keeps its state.** A `folder_judgment` table (root, folder path,
   fingerprint, outcome, reason, evidence summary, judged at) stores every answer and
   every non-pack outcome: `container`, `no_packs`, `mixed` (lossless formation refused),
   `invalid` (failed validation), `error` (search or LLM failure). A `folder_search` table
   caches searches by normalized query. Mixed and invalid folders are shown in the
   command's output and read by `review-items` through `query`; no new review-flag type.
10. **Gate, search, and pooling defaults** (named constants, tuned on the fixtures and a
    catalog copy): a folder is a candidate when non-document files are at least 80% of
    its subtree and it has at least 3 files; the search query is the folder's and its
    parent's words (as `pack_query` builds them), and is skipped when the folder's own
    name is generic (a short list such as maps, tokens, audio, day, night); pooled text
    takes member documents first, then other text, up to a character cap.

## Phases

Each phase ends with the static checks (`ruff check`, `ruff format --check`, `ty check`,
`scripts/check_migrations.py`) plus its own behavior checks. Phases 1 to 5 need no paid
calls.

### Phase 0: pack fixtures

- [x] Add permanent pack-shaped fixtures to `~/data/rpg_test` with an idempotent addition
  to `~/data/rpg_test_tools/add_fixtures.py` (Pillow-drawn images; small generated audio
  or mesh files as `add_fixtures.py` already does):
  - a numbered token run (`Goblin_001.png` … `Goblin_024.png`) with a short license PDF;
  - a map pack with `Day/` and `Night/` (and `Gridded/`, `Gridless/`) variant folders;
  - a pack nested deeper than three levels (`<game>/<publisher>/<pack>/<section>`);
  - a folder dominated by documents (four PDFs and one image);
  - a category folder holding two distinct packs;
  - a duplicate copy of one pack in a second dump.
- [x] Rebuild with `build_smoke.py` and build a new round-1 baseline on the **current
  code** (its `round1` stage), including a "mixed already-filed folder" created by filing
  half of one fixture folder in round 1. Snapshot it separately from the existing smoke
  snapshot.
- [x] Record a **second golden run** on the current code (pre-pack) from that baseline,
  in its own directory (for example `~/data/rpg_test_snapshots/golden-packs/`). The
  existing frozen golden run (`~/data/rpg_test_snapshots/golden`, old pre-entry-table
  code) is kept unchanged (user's decision, 2026-10-02). Phase 2 compares the new code
  against both: the old run on the old fixtures, the second run on the pack fixtures.
- **Verify:** a second `add_fixtures.py` run creates nothing; the existing fixtures are
  byte-unchanged; `build_smoke.py` copies everything; the second golden run completes and
  the original golden directory is byte-unchanged.
- **Unknown:** whether `build_smoke.py`, `restore_smoke.py`, and `golden_ops.py` can point
  at a second snapshot and output directory as they are, or need a small option added.

- **Done 2026-10-02.** `add_fixtures.py` gained `pack_fixtures()`: 108 files in
  `~/data/rpg_test/dump_four/` (`Goblin Warband Token Pack` 24 PNGs + `License.pdf`;
  `Forgotten Crypt Map Pack` Day/Night x Gridded/Gridless x 3 JPEGs + `Read Me.txt`;
  `Fantasy Grounds/Moonlit Press/Sunken Harbor Battlemaps` with `Harbor Maps/` and
  `Harbor Tokens/`; `Assorted Rules PDFs` 4 PDFs + 1 PNG; `Tokens/Undead Token Set` and
  `Tokens/Beast Token Set`; `Downloads Again/Goblin Warband Token Pack`, an exact copy;
  `Dungeon Dressing Tiles` 12 PNGs). The library went from 63 to 171 files. A second run
  creates nothing; no two non-copy fixtures share a hash.
  Tooling: `build_smoke.py --packs` (adds `dump_four`, keeps the first 6 tiles as
  `design-assets / Dungeon Dressing / Dungeon Dressing Tiles`, looks up entry ids, and
  reads `entry.product_id` in its summary); `restore_smoke.py --snapshot NAME`;
  `snapshot_before.py smoke --name NAME`; `golden_ops.py --snapshot NAME`.
  Built on the current code (HEAD `5c8b268` plus the user's uncommitted `clear_errors`
  work, so `--no-code-check`), with a real `enrich`: 175 files (88 unfiled, 26
  duplicates). Snapshot `~/data/rpg_test_snapshots/smoke-packs`; second golden run
  `~/data/rpg_test_snapshots/golden-packs` (15 states). A repeat run of the same ops
  compared IDENTICAL with `diff_runs.py`. The original `golden` directory's file hashes
  are unchanged, and `smoke` is untouched (catalog SHA-256 still `1f24e297…`).

### Phase 1: schema, models, migration `0006`

- [x] `EntryType.pack`; `Pack` model (`id`, `root_id`, `original_root_path`,
  `disposition` (default `unfiled`), `formation` (`find-packs` or `create-pack`),
  `reason`, `evidence` JSON, timestamps); `entry.pack_id` (unique, `ON DELETE CASCADE`);
  `file.pack_id` (indexed, `ON DELETE RESTRICT`); `FolderJudgment` and `FolderSearch`
  models. No unique index for decision 7 (it is enforced in the services).
- [x] Migration `0006` in the `0005` style. `entry` is rebuilt to add `pack_id` and a
  CHECK that exactly the right foreign key is set for each `type`. Downgrade dissolves
  packs: each member gets a file entry carrying the pack's product, and the pack's
  disposition is written to `file.disposition`; then the new tables and columns go.
- [x] `entries.py`: helpers that return an entry's kind and members; `file_entry` callers
  that can meet a member get an optional variant.
- **Verify:** `scripts/check_migrations.py`; `migrate_copy.py` on a smoke copy and on a
  copy of the full catalog, then `compare_catalogs.py` (expect EQUIVALENT: no content
  changes, since no packs exist yet); a round trip `0006 → 0005 → 0006` restores schema
  and rows (`schema_diff.py`, `rows_equal.py`); a hand-made pack on a smoke copy survives
  downgrade as file entries with the pack's product and disposition.

- **Done 2026-10-02.** New models `Pack`, `FolderJudgment`, `FolderSearch` and enums
  `PackFormation`, `FolderOutcome`; `Entry` gained `pack_id`, `uq_entry_pack_id`, and the
  `ck_entry_one_item` CHECK; `File` gained `pack_id` (RESTRICT, indexed). Migration
  `0006_add_packs.py` (entry rebuilt as in 0005; `file` via `batch_alter_table`). The
  `entries.py` helpers are added in phase 2, where their callers are.
  Checked: `scripts/check_migrations.py` (migrations match the models); ruff, ruff
  format, ty clean. `migrate_copy.py` up to 0006 on the smoke-packs catalog and on a copy
  of the live catalog: `rows_equal.py` against the 0005 copies differs only in
  `alembic_version` and the three new, empty tables. Down to 0005 again: `schema_diff.py`
  SCHEMAS MATCH and `rows_equal.py` ROWS IDENTICAL (22 tables) for both. A hand-made pack
  (10 Beast tokens, `keep`, a product, a google error on its entry) on a smoke copy:
  deleting the pack is refused (RESTRICT), an entry with both keys is refused (CHECK);
  after downgrade the 10 files have file entries with the pack's product, disposition
  `keep`, and no pack entry or orphan error remains. The live catalog's hash was unchanged.

### Phase 2: pack-aware readers, with no packs yet

Make every site that silently drops packs aware of them, while no packs exist, so the
loose-file behavior is proven unchanged.

- [x] `services/placement.py`: load members through their pack (effective disposition =
  `pack.disposition`, product = pack entry's `product_id`); `kept_counts` and
  `paths.kept_file_count` count kept members; members get their subpath relative to the
  pack's current root (deepest common folder of its members) unless a subpath is stored;
  members still count toward `products_below` so other files' flattening rules see them.
- [x] `commands/reorganize.py`: key `by_id`, `blocked`, and collisions by file id; carry
  the entry id for error rows (decision 8).
- [x] `services/pending.py` follows placement (no change expected beyond placement).
- [x] `services/lists.py`: `list_unfiled` excludes members, and lists unfiled packs as
  items of their root folder (`entry_id`, root folder, member count, hint); kept counts
  in `list_product_types` include members.
- [x] `services/reports.py`: `_files_summary` and `report_product` list a product's pack as
  one item with its member count; `report_line` counts include members; `target_folder`
  follows `kept_file_count`.
- [x] `commands/enrich.py`: `_eligible` yields pack contexts as well as file contexts (see
  phase 6; until then packs are simply skipped) and does not pass a file id to
  `FileTracker` for a pack.
- [x] `commands/scan.py`: decisions 4 and 5 (entry-optional clear and reset steps,
  detach-on-error, members never demoted).
- **Verify:** `golden_ops.py --no-code-check` on the new code, then `diff_runs.py` against
  both golden runs (the original and the phase 0 second run): expect identical states (extend `catalog_state.py` to skip the new
  tables while they are empty, as it already skips `entry`); `tool_checks.py` (normal and
  `--prepare offset`) passes; `compare_reports.py` and `snapshot_placements.py` on a copy
  of the full catalog show 0 differences after `migrate_copy.py`.

- **Done 2026-10-02.** New `services/pack_info.py` (a pack's derived current root and
  member counts) and `membership.py` (join, detach, delete-if-empty, own-entry: the one
  place membership changes). `placement.py` loads members through their pack and
  places them relative to the pack's current root; `paths.kept_file_count` and
  `list_product_types` count kept members; `reorganize` keys by file id and writes one
  summary `reorganize` error per pack (`PackFailures`); `list_unfiled` lists unfiled packs
  in the folder that is their current root (`total_unfiled_packs`, `packs`,
  `direct_packs`/`subtree_packs`); `report_product` adds `packs` (only when the product
  has some) and `report_line` counts members; scan follows decisions 4 and 5 (a
  stage error on a member detaches it via `own_entry`; `_clear_errors`,
  `_clear_scan_rows`, `_reset_judgment` handle entry-less members; `_join_duplicates`
  skips members). `enrich._eligible` needed no change yet: its join on `entry.file_id`
  already leaves out members and pack entries (pack enrichment is phase 7).
  Out-of-repo tools: `catalog_state.py` and `compare_catalogs.py` know pack keys and
  report `packs` only when packs exist; `snapshot_placements.py` drops a `None`
  `pack_id`.
  Checked: ruff, ruff format, ty clean. `golden_ops.py --no-code-check` on the new code:
  IDENTICAL to both the original `golden` run and `golden-packs` (all 15 states).
  `tool_checks.py` 37/37 and, with `--prepare offset`, 41/41. On a copy of the live
  catalog, the committed code (a `git worktree` of HEAD at `/tmp/wt-head`) on 0005 and
  the new code on 0006: placements for all 34,252 files byte-identical; sampled reports
  (131 files, 28 products, 28 lines) identical except the new `total_unfiled_packs: 0`
  in the two `list_unfiled` outputs.

### Phase 3: pack services and tools

- [x] Services (new `services/packs.py`): create, add, remove (file or folder path),
  report-pack, empty-pack deletion, all in one transaction per call (decisions 1 to 3,
  6). `create-pack` takes the shared product and disposition when the files agree, and
  otherwise requires `product_type`, `product_line`, `product`, and `disposition`
  (reusing `update_product`'s resolution).
- [x] `update_product`: accept pack entries (set `pack.disposition` and the entry's
  product; clear members' stored subpaths when either changes), mixed batches of file
  and pack entries, the one-pack-per-product message, and review flags on pack entries.
- [x] `report_entry`: dispatch on type; the pack summary from intent (root, member counts
  by media type, top-level subfolders with counts, a few sample filenames, pooled
  evidence, product, disposition, errors, review flag, `pending_changes`).
- [x] `rename-file`: unchanged rule (file entries only); its message mentions packs.
- [x] MCP tools in `server/tools.py` (`create_pack`, `add_to_pack`, `remove_from_pack`,
  `report_pack`, with docstrings the agent can act on) and CLI mirrors in
  `commands/tools.py` and `__main__.py`.
- [x] `services/schema.py`: table notes for `pack`, `folder_judgment`, `folder_search`,
  and the new columns; example queries that cover pack entries.
- **Verify** on a smoke copy, through the real MCP wrappers (extend `tool_checks.py` the
  way it was built for the entry table): create a pack from the token fixture; report it
  (`report_entry` stays small, `report-pack` lists everything); file it with one
  `update_product`; add and remove a file and a folder; move a file between two packs;
  empty a pack and see it deleted with its entry and evidence; add a loose file filed to
  another product and see the dropped decision listed in the output; get refused for a
  second kept pack on one product (while a superseded pack on the same product is
  accepted), a duplicate, and a file id passed as an entry id (with
  `--prepare offset`).

- **Done 2026-10-02.** `services/packs.py` (`create_pack`, `add_to_pack`,
  `remove_from_pack`, `report_pack`, `pack_report_entry`; paths resolve to one root, a
  folder's duplicates and missing files are skipped and listed, a named duplicate is
  refused). `create-pack` with a decision files the new pack through `update_product`;
  without one it takes the files' shared decision (refusing, with examples, when they
  differ). `dropped_decisions` lists only decisions that differ from the pack's.
  `update_product` files pack entries (disposition on `pack`, members' stored subpaths
  cleared on a change) and refuses a second *kept* pack for a product
  (`_check_one_kept_pack`). `report_entry` dispatches to the pack summary. MCP tools
  `report-pack`, `create-pack`, `add-to-pack`, `remove-from-pack` and CLI mirrors;
  schema notes (`pack`, `folder_judgment`, `folder_search`, member joins) and example
  queries that include packs; server instructions describe packs.
  Checked: ruff, ruff format, ty clean. New out-of-repo `pack_tool_checks.py` (real MCP
  wrappers and CLI on the `smoke-packs` state): 42/42, and 42/42 with
  `--prepare offset`. Fixture note: scan walks `Downloads Again/` first, so that copy is
  the original and the `Goblin Warband Token Pack/` copy is the duplicate (trashed in
  the baseline).

### Phase 4: placement and reorganize with packs

- [x] Check (and fix as needed) that `reorganize --dry-run` and `reorganize` move a filed
  pack's members into `<type>/<line>/<product>/<path below the pack root>`, apply trash
  dispositions to members, store members' subpaths at the first move, and record blocked
  members on the pack entry.
- **Verify** on a smoke copy: file the token and Day/Night packs; `reorganize --dry-run`
  matches `pending_changes`; a real `reorganize` produces the expected tree (variant
  folders kept, no extra pack-named folder); a pack plus a loose PDF of the same product
  share the product folder; a second `reorganize` moves nothing; a deliberately blocked
  destination produces one error on the pack entry and per-file output.

- **Done 2026-10-02.** No code change was needed beyond phase 2. New out-of-repo
  `pack_reorganize_checks.py` (CLI on the `smoke-packs` state): 15/15. Token pack lands
  flat in `design-assets/Inkwell Tokens/Goblin Warband/` (25 files); the crypt pack keeps
  `Day|Night/Gridded|Gridless/` under `maps/Crypt Maps/Forgotten Crypt/` with no extra
  pack-named folder, and a loose PDF filed to the same product sits beside it; the
  emptied source folder is pruned; every moved member has a stored subpath; a second
  run moves nothing; a superseded pack's 24 tokens go to `.trash/superseded/`; one
  occupied destination gives one summary `reorganize` error on the pack's entry
  ("1 member file(s) of this pack could not be moved: …"), the output names the file,
  the other members move, and once unblocked the member moves and the error clears.
  Dry run: to-move plus blocked equals `pending_changes` (the baseline's Play Dirty
  block counts in both).

### Phase 5: scan with packs

- [x] Auto-join: after extraction and the duplicate join, a *new* file (not a move, not a
  duplicate) whose folder is under a pack's current root or original root (same root)
  joins that pack; the deepest matching pack wins. Its fresh entry is removed.
- [x] Member rescans per decision 4; duplicate join per decision 5.
- **Verify** on a smoke copy with packs: add a new token to a pack folder and `scan` (it
  joins; no entry created); add a copy of a member elsewhere (it becomes a duplicate of
  the member, the member stays); change a member's bytes (it stays in its pack); corrupt
  a member (it is detached with a scan error on its own entry); `scan --force` over packs
  raises no `LookupError`; a file removed from a pack does not rejoin on rescan.

- **Done 2026-10-02.** `scan` auto-join (`Scanner._auto_join`, `_pack_for`): a new,
  non-duplicate, error-free file joins the deepest pack whose current or original root
  holds its folder; a pack rooted at a whole root folder is never joined this way.
  Deviation found by the checks: the duplicate join preferred a library copy as the
  winner, so a new copy of a member could become a duplicate of an old *trashed* copy
  (which was then un-duplicated). The winner ranking now puts pack members first
  (behavior without packs is unchanged), which is what decision 5 intends.
  Checked: ruff, ruff format, ty clean. New out-of-repo `pack_scan_checks.py`: 16/16
  (new token joins with no entry; a new file in a new subfolder joins; a copy of a
  member elsewhere becomes the member's duplicate and the member stays; a changed member
  stays; a zero-byte member PDF is taken out with its error on its own entry; `scan
  --force` keeps all 39 members; a removed file does not rejoin; every file has an
  entry or a pack, never both). Both golden comparisons re-run after the scan changes:
  IDENTICAL.

### Phase 6: `find-packs`

- [x] New command `find-packs` (`commands/find_packs.py`) with `--root`, `--limit` (LLM
  calls), `--dry-run` (classify and report, create nothing), and `--no-search`.
- [x] Evidence summaries from the catalog only (no filesystem walk): per folder, direct
  and subtree counts by media type, numbered-name runs (shared stem plus number, with
  counts), sibling folders that look like variants (same file stems or counts across
  siblings; names like day/night, gridded/gridless, png/jpg), child folder names with
  subtree counts (capped).
- [x] Gate (decision 10), skipping settled folders: those with no unfiled loose,
  non-duplicate, present files below them.
- [x] Folder search through the existing Serper client, cached in `folder_search`.
- [x] Top-down LLM classification through litellm, using the same model setting as text
  analysis (`RPG_LIBRARIAN_LLM_MODEL`) and a structured answer per folder: `pack`,
  `container` (with the children to descend into), or `no_packs`, with a reason; siblings
  batched in one call; answers stored with fingerprints (sorted paths and sizes below the
  folder) and reused while unchanged. Existing packs are never re-judged.
- [x] Validation (paths exist, no overlap, each file claimed once, not a duplicate),
  lossless formation, pack creation, and copying the cached search into the pack's
  `google_search_result`.
- [x] Output: packs created, folders recorded as mixed, invalid, or failed, calls spent.
- **Verify** on a smoke copy (paid, small): `find-packs --dry-run` then `find-packs` on
  the fixtures: the token, Day/Night, and deep packs form with their variant folders
  inside; the documents folder is gated out without a search or LLM call; the category
  folder yields two packs; the duplicate copy forms no pack; the half-filed folder is
  recorded as mixed; a second run makes no search or LLM calls. Then a dry run on a copy
  of the full catalog with `--limit` to measure the real search and call counts against
  the 4,412 folders (expect far fewer: most are filed).

- **Done 2026-10-02.** `find_packs/evidence.py` (catalog-only folder tree; eligible and
  unsettled files; gate `MIN_FILES = 3`, `MEDIA_SHARE = 0.8`; fingerprint of paths and
  sizes; numbered runs; variant subfolders by name pairs or shared file names; generic
  names that skip the search; evidence summaries), `find_packs/judge.py` (litellm,
  same model setting as text analysis, structured `pack`/`container`/`no_packs`
  answers), `commands/find_packs.py` (top-down walk, stored-answer reuse, sibling
  batches of up to 10, validation, lossless formation, one kept pack per product,
  `folder_judgment` and `folder_search` writes, Google evidence copied to formed packs)
  and the CLI verb with `--root`, `--limit`, `--dry-run`, `--no-search`. The Serper call
  moved to `enrichment/google.serper_search` (shared; `enrich` unchanged) and the
  folder-word query builder to `queries.folder_words`.
  Design detail settled here: a `--dry-run` stores its answers and searches, and a
  later real run forms the proposed packs from them without asking again while the
  folders are unchanged.
  Checked: ruff, ruff format, ty clean. Offline, with a stub model and `--no-search`:
  only the five `dump_four` candidates are asked (documents folder gated out; settled
  and trashed folders skipped; numbered runs and Day/Night variants detected).
  New out-of-repo `pack_find_checks.py` (PAID), 20/20 with search and 20/20 with
  `--no-search`: the dry run asked 5 calls about 10 folders (8 searches, 2 skipped as
  generic); the real run asked nothing and searched nothing; packs formed for the
  goblin (25), crypt (13, variant folders inside), deep harbor (8), undead (10), and
  tiles (6) folders; no pack from the documents folder; the half-filed Beast folder
  recorded `mixed` and left loose; trashed duplicates never members; formed packs
  carry their folder search; a second run asks nothing.
  On a copy of the live catalog, `find-packs --dry-run --limit 10` asked nothing: the
  live catalog has no unfiled files (33,109 keep, 762 duplicate, 363 discard, 18
  superseded), so every folder is settled. The real search and call load depends on
  how pack-migration adopts filed products, so it is measured there, not here.

### Phase 7: enrichment for packs

- [x] Pack contexts in `enrichment/queries.py` (root folder, parent folder, member PDF
  titles, pooled samples) and `wants`/`fetch` for packs in dtrpg and rpggeek (ladder:
  root folder name, parent name, their combined words, then member PDF titles), Google
  (already covered by `find-packs`; otherwise searches the root and parent words), text
  analysis (pooled text, pack prompt), and never ISBN.
- [x] `enrich` progress and logs name the pack's root for pack entries.
- **Verify** on a smoke copy with packs: `enrich --limit` per source makes one request
  per pack, not per member; Google makes none for packs `find-packs` created; text
  analysis gets a description from a pack with a license or readme PDF; loose files are
  enriched exactly as before (compare their evidence rows to the golden run's).

- **Done 2026-10-02.** `FileContext` carries a pack (`PackFacts`: root folder, parent
  folder, member PDF titles; `file_id` None; `sample_pages` the pooled text);
  `queries.pack_ladder` and `pack_google_query`; dtrpg and rpggeek want packs and use
  the ladder; Google searches a pack's parent and root words (when `find-packs` has not
  already stored a row); text analysis pools members' samples (documents first,
  `POOLED_TEXT_CHARS = 12_000`, keys `<path in pack>#<page>`) with a pack prompt, while
  the loose-file prompt is byte-identical to the committed one (checked against the
  HEAD worktree); ISBN never runs for packs (file-keyed tables get no pack contexts).
  Checked: ruff, ruff format, ty clean. Offline, on the `smoke-packs` state with three
  hand-made packs: only the 3 packs are eligible (every loose file is already
  enriched); ladders and pooled keys as designed. PAID `enrich` with one pack given a
  Google row first: isbn 0, dtrpg 3, rpggeek 3, google 2 (the covered pack skipped),
  text analysis 2 (the tokens' license and the crypt's readme give pack descriptions;
  the harbor pack has no text). The fixtures are fictional, so dtrpg and rpggeek find
  nothing, as expected. Loose files' evidence rows unchanged (103 google, 31 dtrpg, 36
  text analysis). `tool_checks.py --enrich` (loose-file enrich): 41/41.

### Phase 8: skills, README, and an end-to-end run

- [x] `process-batch`: step order (`scan`, `find-packs`, `enrich`), packs in the
  worklist, filing a pack with one `update_product`, when to use `create-pack`,
  `add-to-pack`, and `remove-from-pack`, and that pack evidence identifies the pack.
- [x] `review-items`: SQL that covers pack entries (no `en.file_id = f.id` inner joins
  where packs must appear), mixed and invalid folders from `folder_judgment`, blocked
  pack members.
- [x] `README.md`: `find-packs`, the new tools, and the step order. Note that libraries
  that ran `init` keep old skill copies: delete them and re-run `init`.
- **Verify:** `check_skill_sql.py` runs every SQL block in both skills against a smoke
  catalog with packs; one end-to-end run on a fresh smoke copy (`scan`, `find-packs`,
  `enrich`, `process-batch` through an MCP client, `reorganize`, `review-items`)
  completes, with the result checked against each acceptance condition below.

- **Done 2026-10-02.** Both skills updated (`process-batch`: packs section, step
  order, pack-aware review query and rules; `review-items`: a third queue for folders
  `find-packs` left loose, pack-aware SQL, pack members as occupants, `remove-from-pack`
  as a resolution); README (step order, the pack tools, a Packs section, enrich for
  packs, re-`init` note for stale skill copies).
  Checked: new out-of-repo `pack_skill_sql.py` ran all 10 SQL blocks (both skills and
  the `describe_schema` examples) on a catalog with packs, a pack review flag, a pack
  `reorganize` error, and a `mixed` judgment: all run, and pack rows appear where they
  should. The old `check_skill_sql.py` compares old and new query lists one-for-one, so
  it no longer applies (the skills have more queries now). New out-of-repo
  `pack_e2e.py` (PAID), twice: a new `round3/` dump; `add-source`, `scan`,
  `find-packs` (1 call, 2 searches, 2 packs formed), `enrich` (the token pack's readme
  gives its description), filing through the real MCP tools in the `process-batch`
  order, `reorganize` (both packs in their product folders with their variant and
  asset folders), and the review SQL: 20/20.
  **Limitation:** filing was a scripted stand-in for an agent following the skill; no
  agent session ran `process-batch` or `review-items` themselves.
  Final regression on the finished code: ruff, ruff format, ty, migrations check clean;
  both golden runs IDENTICAL; `tool_checks.py` 37/37 and 41/41 (offset);
  `pack_tool_checks.py` 42/42 and 42/42 (offset); `pack_reorganize_checks.py` 15/15;
  `pack_scan_checks.py` 16/16; full-catalog placements still byte-identical to the
  committed code; the live catalog's hash unchanged and still at `0005`.

### Follow-up fix after review (2026-10-02)

- [x] A dissolved pack is never re-formed by `find-packs`. Previously a pack that
  `find-packs` formed and someone then emptied with `remove-from-pack` kept a
  `folder_judgment` row (outcome `pack`, `pack_id` NULL). The next run mistook that for a
  dry-run proposal and formed it again, overruling the correction. Now a stored `pack`
  answer is formed only when `details.proposed` is true. Deleting a pack
  (`membership.delete_if_empty`) also records its folders as `no_packs` ("dissolved")
  at their current fingerprint: where it was formed, any answer that formed it, and its
  current root (passed by `remove-from-pack`). So a hand-made pack's folder is not asked
  about again either, until its contents change.
- [x] A one-member pack's derived root is just that file's folder; a kept one sits
  flat in its line folder. Scan's auto-join and `find-packs` now use a pack's derived
  root only when it has at least 2 present members, and otherwise only its original
  root. Before, a new file anywhere in the line folder could have joined such a pack,
  and `find-packs` could have skipped the whole line.
- **Checked:** new out-of-repo `pack_dissolve_checks.py` (offline, stub model, no
  search): 11/11. A dissolved find-packs pack and a dissolved hand-made pack are not
  asked about or re-formed; a changed folder is asked about again; dry-run proposals
  still form without asking; a one-member kept pack does not take a new file in its
  line folder. Re-run after the fix: both golden runs IDENTICAL, `tool_checks.py` 37/37
  and 41/41, `pack_tool_checks.py` 42/42 and 42/42, `pack_reorganize_checks.py` 15/15,
  `pack_scan_checks.py` 16/16; ruff, format, ty, migrations check clean.

## Acceptance conditions and where they are checked

| Condition (from intent.md) | Phase |
|---|---|
| `find-packs` finds the packs a person would name, keeps variant and section folders inside one pack, and forms no pack from a documents folder | 6 |
| A pack of many generic files is filed with one `update_product`, and `reorganize` moves all its members under the product folder with the pack's disposition | 3, 4 |
| A pack with no search matches is still filed and placed from its folder name | 6 (`--no-search`), 4 |
| One lookup per pack, and `enrich` does not repeat the `find-packs` Google search | 7 |
| `report_entry` on a pack stays small; `report-pack` lists everything | 3 |
| Add, remove, and create work on files and folders; an emptied pack is deleted; a correction survives `scan`, `find-packs`, and `enrich` | 3, 5, 6, 7 |
| A second kept pack for an already-packed product is refused | 3 |
| `process-batch` and `review-items` complete a run that includes packs | 8 |

## Quality rubric

The approved rubric is in [intent.md](intent.md#quality-rubric). Where the plan serves
each dimension, and where evidence will come from:

- **Pack integrity:** phases 4 to 6 (members move as one, variants stay inside, overlap
  validation, members never demoted). Evidence: the phase 4 tree and phase 6 fixtures.
- **Evidence fidelity:** phases 1, 3, 6 (stored reasons and evidence, lossless joining and
  formation). Evidence: `report_entry` on packs; mixed folders recorded, not forced.
- **Usefulness with sparse evidence:** phases 6 and 7 (`--no-search`, folder-name
  ladder). Evidence: filing a fixture pack with no hits.
- **Processing economy:** phases 6 and 7 (gate, caches, fingerprints, one lookup per
  pack). Evidence: the call counts measured in phase 6 on a catalog copy.

## Material unknowns

- Whether the LLM's top-down answers are good enough on real dumps; only phase 6 on a
  catalog copy will show it. The gate thresholds and generic-name list will need tuning.
- The real number of searches and calls on the live catalog (measured in phase 6).
- Whether `catalog_state.py` and `diff_runs.py` need more than skipping empty new tables
  to compare phase 2 runs.
- How the live catalog adopts packs is out of scope here; [pack-migration](../pack-migration/item.md)
  depends on phases 1 and 6.
