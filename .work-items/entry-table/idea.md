# Entry table refactor: idea

Workshop outcome of 2026-10-02. The refactor itself is not built. Items marked
**(agreed)** were accepted by the user. The [review findings](#review-findings-2026-10-02)
are the agent's and **not yet confirmed** by the user. This supersedes the earlier
asset-pack workshop and discussion, which were deleted.

## Intended effect

Prepare for working with packs (collections of files) as first-class catalog objects
without building packs now. The catalog and tools should work natively on *entries*, so
that adding a `pack` entry type later means a new table, a new foreign key, and a new
`type` value, not another reshape. The change is a pure refactor: no behavior changes,
and an existing database migrates to the new structure with no loss.

## Working direction (agreed)

### The `entry` table

- `entry(id, type, file_id)`: a discriminated union. `type` says which foreign key to
  read. Today the only type is `file`; a `pack` type and a `pack_id` foreign key are
  added when packs arrive.
- `entry.product_id` replaces `file.product_id`: the product link moves to the entry.
- `disposition` **stays on `file`** (user's decision, on the agent's recommendation).
  Consequence: the check `disposition != 'keep' OR product_id IS NOT NULL` cannot span
  tables, so it is **dropped**. `update_product` already rejects `keep` without product
  coordinates and continues to enforce the rule.
- The migration seeds `entry.id = file.id`, so every existing ID stays valid. After that
  the two ID spaces are independent; code must never assume `entry.id == file.id`.
- Scan creates the entry whenever it creates a `File`. Its "content changed" reset
  clears `entry.product_id`.

### Re-keying to `entry_id`

Six tables change from `file_id` to `entry_id`, values unchanged (user chose to include
`error` and `review_flag`):

1. `google_search_result`
2. `dtrpg_result`
3. `rpggeek_result`
4. `file_text_analysis`
5. `error` (primary key becomes `(entry_id, stage)`)
6. `review_flag` (the partial unique index on open flags is rebuilt on `entry_id`)

Stay file-keyed because they describe file contents: `isbn_result`, `file_text`,
`file_metadata`, and the per-media metadata tables.

Reasons for including `error` and `review_flag` (agent's recommendation, accepted):
errors and evidence describe the same item, so one key lets `enrich` use a single ID per
item; packs need entry-keyed errors and flags anyway, so re-keying now avoids a second
migration; `update_product` receives entry IDs and opens one flag per entry. Scan and
`reorganize` errors are file-level but still work, because every file has an entry.
`file_text_analysis` shares `FileMetadataBase` with file-keyed tables today, so it and the
evidence tables need a new entry-keyed base class. **Decided (agreed):** add
`EntryMetadataBase` in `model/core.py` next to `FileMetadataBase`, with `entry_id` as the
primary key and a cascading foreign key to `entry.id`. `EvidenceBase` and `FileTextAnalysis`
extend it; `FileMetadataBase` stays for the file-keyed tables; `Error` and `ReviewFlag`
define their own columns and just rename `file_id` to `entry_id`.

### Approach: translate at the edge

- Services and tools accept entry IDs and resolve to `File` through `entry.file_id`.
- `scan`, `reorganize`, `isbn_result`, and the metadata tables stay file-based except where
  they touch `product_id` or the six re-keyed tables.
- `enrich` still loops over files. `FileContext` gains the file's `entry_id`, used when
  writing evidence and error rows.
- `product_id` touches about 40 places: `update_product`, `reports`, `lists`, `placement`
  (and so `reorganize`), `paths`, `rename_file`, scan's reset, SQL in the `review-items`
  skill, and the schema notes.

### MCP tools

`process-batch` never sees a file ID.

| Tool | Change |
|---|---|
| `list_unfiled` | Returns entry IDs. |
| `report_file` | **Renamed `report_entry(entry_id)`** (agreed). Returns the file shape now and dispatches on `type` when packs arrive; every response carries `type`. This reverses the agent's earlier advice to keep separate file and pack reports, because the agent now holds only entry IDs. |
| `update_product` | Takes `entry_ids`; a review flag opens against the entry. |
| `rename-file` | Takes `entry_id`, stays file-only and rejects non-file entries. |
| `list_product_types`, `list_product_lines`, `report_product`, `report_line`, `describe_schema`, `query` | Behavior unchanged; `describe_schema` notes and the skills' SQL follow the new schema. |

The CLI arguments and the `process-batch` and `review-items` skill text follow the
renames.

### Product type seed list

`SEED_PRODUCT_TYPES` in `product_types.py` is out of date against the live catalog
(`~/data/rpg-librarian`): add **`design-assets`**. `fonts` is already gone from both.
`init` only inserts missing types, so the live database needs no migration for this.
Types the LLM creates at runtime remain allowed.

## Verification (agreed)

Per the project policy, no new unit tests; use direct behavior checks.

1. **Smoke test** on `~/data/rpg_test` (note the underscore; `~/data/rpg-test` does not
   exist): process it with the current code, snapshot the database, migrate a copy, run
   the same checks through the new code, and compare.
2. **Full snapshot test** on a copy of `~/data/rpg-librarian` (about 545 MB). Never touch
   the live catalog.

Compare: row counts per table; every re-keyed `entry_id` maps back to the same file;
per-file `product_id`, `disposition`, and evidence through the entry join; the desired
placement of every filed file (the most important check, since it exercises the
`product_id` move; see the placement check below for why this replaced the `reorganize`
dry-run as the primary check); and a few `report_file` versus `report_entry` outputs
differing only in renames. Only expected ID and field renames may differ. `enrich` need not be re-run
after migration, since the migration only has to preserve existing data.

### Enhancing the smoke-test library (agreed: the user approved all seven items)

`rpg_test` today holds 55 files (20 PDF, 14 STL, 13 OGG, 6 AI, 1 TXT, 1 LYS) in three
dump folders and an **empty `Library`**. Proposed additions, by risk:

1. Put filed products into `Library` (run `reorganize` once, then add a second round of
   files) so stored `subpath` and library placement are exercised.
2. Cover every filing state: multi-file and single-file `keep`, `superseded` with and
   without coordinates, `discard`, open and resolved review flags.
3. Add an automatic duplicate, two files colliding on one target path, and a file that
   goes missing between scans.
4. Make sure all four evidence types and text-analysis rows exist, plus a no-match row.
5. Add errors: a corrupt or zero-byte PDF and a truncated OGG.
6. Add types the dumps lack: a few images and a `.webp`.
7. Add an accented or awkward filename to exercise `sanitize_name`.

To control cost, process once with current code and snapshot; re-running `enrich` after
migration is unnecessary.

**What the files already cover (checked 2026-10-02).** Covered: multi-file products with
subfolders (Miniature Holder, Cyberpunk Music Pack, The Sprawl), single-file products, and
the PDF/OGG/STL/AI/TXT/LYS mix; "copy"-style and generic names are partly covered
(`BattlfinderAm1 copy.ai`, `010101.ai`). Not covered: a populated `Library`, an automatic
duplicate (zero duplicate hashes), zero-byte or corrupt files, awkward filenames (all
ASCII), and images. Evidence coverage (all four types, text analysis) is unknown until the
first `scan` and `enrich`. Filing states, flags, errors, collisions, and a missing file
come from how the pipeline is driven, not from file properties.

**Fixtures (agreed; changed 2026-10-02):** the static fixture files are now added
permanently to `~/data/rpg_test` (see plan.md step 2), not generated into each build. The
original plan was to generate the missing files from existing ones with a small
throwaway script (a `cp` for the duplicate, cut-down copies for corrupt and truncated
files, a renamed copy for the awkward name, Pillow for images if installed), and drive the
filing states with a scripted `update_product` sequence after the first `scan` and
`enrich`. The script lives **outside the repo** next to the fixtures (for example
`~/data/rpg_test_tools/`), because it is single-use tooling and the project avoids adding
test infrastructure. It is not written yet. The smoke test registers `rpg_test` with its
own roots (`add-source`), so real `reorganize` runs there are harmless.

## Full-copy safety and the placement check (agreed)

The live roots exist on this machine: `/phinneas/rpg/library` (34,243 files, 33,109 kept)
and `/phinneas/rpg/inbox` (50 files, all marked missing because they were moved). Because
the library is already in place, `reorganize --dry-run` reports almost nothing to move, so
it cannot reveal a broken `product_id` join. The primary check on the full copy is
therefore a before/after diff of `services.placement.compute_placements` (the desired
location of every filed file); `--dry-run` is secondary and should show no change.

A copied database still points at the real `/phinneas/...` paths. On the full copy run
only `--dry-run` and the placement diff, never `scan` or a real `reorganize`.

## Verification tools (built and tested 2026-10-02)

Both are in `~/data/rpg_test_tools/`, outside the repo.

- `compare_catalogs.py BEFORE.db AFTER.db`: read-only, stdlib-only, runs on either schema.
  Matches files by `(root path, relative path)`, never id. Checks structure (six tables on
  `entry_id`, the rest on `file_id`, `entry` present, `product_id` moved), entries (one
  `file` entry per file, no orphans), row counts, every `file` row (columns, duplicate
  target, product coordinates), every other table row by row through its owner, and
  optionally placements. `--strict-ids` also requires per-file table `id`s unchanged;
  `--skip-product-move-check` is for hand-built test databases. Exit 0 only if equivalent.
- `snapshot_placements.py DB OUT.json`: writes `compute_placements` output keyed by root
  path and relative path. Run once per side with the matching checkout
  (`uv run --project <checkout> python ...`), then pass both files to the compare script.

Tested on a copy of the live catalog with a hand-built simulated post-migration database:
all checks pass in about 4 seconds on 34,293 files, and six injected defects (wrong
product on an entry, evidence re-pointed to the wrong entry, missing entry, changed
evidence text, changed disposition, swapped entry-to-file mapping) were each caught. Not
yet run against a real migrated database, since the migration does not exist.

## Review findings (2026-10-02)

A final review of this proposal against the code and the live catalog. These are the
agent's recommendations and observations, not yet confirmed by the user; none changes an
agreed decision.

1. **Constrain `entry` itself (agreed 2026-10-02).** The user approved all three
   constraints below, and leaving out a check that `type` matches the filled-in foreign key
   (it would need rewriting for every new entry type; the compare script already checks
   that every entry is of type `file`). Add `UNIQUE (file_id)` so a file cannot
   get two entries; the compare script checks this, but the schema should enforce it. Index
   `entry.product_id`, which replaces the indexed `file.product_id` used by placement and
   reports. Cascade deletes from `file` to `entry` to match how per-file rows cascade today
   (nothing deletes files now, so this changes no behavior).
2. **Copy `product_id` unconditionally (observation).** In the live catalog, 198 `discard`
   and 18 `superseded` files carry a product link besides the 33,109 kept files. The
   migration must copy every non-null `file.product_id`, not only kept ones. The compare
   script would catch a miss.
3. **An unreachable branch becomes reachable (observation).**
   `services/placement.py:101` skips a kept file with no product, with a comment saying the
   CHECK constraint makes this unreachable. This change drops that constraint. Behavior stays the same (the file is
   skipped), but the comment should now cite `update_product`'s validation. The placement
   diff would show any file skipped this way.
4. **Migration target (observation).** The live catalog is at alembic revision `0004`, so
   this is revision `0005` in `apps/rpg-librarian/src/rpg_librarian/alembic/`. The legacy
   `packages/rpg-librarian-mcp` migrations, which also mention an entry table, are
   unrelated.
5. **Make ID spaces diverge in the smoke test (agreed 2026-10-02, in the form below).**
   Seeding
   `entry.id = file.id` plus SQLite's rowid allocation means newly scanned files will
   usually get matching entry and file IDs too. Code that passes a file ID where an entry
   ID belongs would then pass every check by accident. The smoke test should force the
   spaces apart on its migrated copy (for example, advance the entry ID sequence before the
   second-round scan) and then exercise the tools. The compare script matches by path, so
   it is unaffected.

   **Decided form:** a test-only tool, `renumber_entries.py`, run on a migrated copy only,
   adds a large offset (for example 100,000) to every `entry.id` and to `entry_id` in the
   six re-keyed tables. The tools are then run against both the normal migrated copy (IDs
   equal, proving the migration preserves the data) and the offset copy (IDs different,
   proving the code never relies on equality: a file ID passed as an entry ID now matches
   no entry and fails loudly, and a swapped lookup returns a wrong row that the path-based
   compare catches). The migration itself still seeds `entry.id = file.id`. Advancing the
   counter before the round 2 scan was rejected: it needs placeholder entries and cannot
   cover the existing rows.

## Working quality dimensions (not an approved rubric)

Behavior preservation; smallness (churn and review surface); future fit (packs slot in
without another reshape); migration safety. Judged on the design's apparent potential:
behavior preservation and smallness are good, future fit is good, and migration safety is
good in design but untried on real data until the verification above runs.

## Assumptions

- The migration can rebuild the six tables with a SQLite batch alter and copy values
  without loss; not yet attempted.
- `~/data/rpg_test` plus a copy of the live catalog are representative enough to expose
  `product_id` join mistakes.

## Open questions

No design questions remain. Still to settle or do:

- Findings 1 and 5 are agreed. Findings 2 to 4 are observations for the migration phase.
- Which of the seven fixture items the first `scan` and `enrich` of `rpg_test` still
  leaves uncovered (notably evidence coverage), once it has been processed.
- The fixture script and the scripted filing sequence still need writing.
