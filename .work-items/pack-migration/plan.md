# Pack migration: five-phase process

Agreed process, refined and accepted in workshop on 2026-10-03. Bring the live catalog at
`~/data/rpg-librarian/catalog.db` to schema `0006`, then adopt already-filed asset
products as packs while preserving their effective product, disposition, and placement.
This document records the agreed sequence, the verification it needs, and the four
design decisions settled on 2026-10-03 (see the end). No phase has run in this item.

See [background.md](background.md) for the handoff, prior checks, and reusable tools,
and [asset-pack-support/intent.md](../asset-pack-support/intent.md) for pack behavior.
The accepted migration checks and their rationale are in [checks.md](checks.md).

## Accepted workshop refinements

The five phases stay in their original order. Three changes strengthen the connection
between rehearsal, validation, and live execution:

1. **Fix adoption decisions during rehearsal; reuse them on live.** Phase 4 produces
   a reviewed adoption list specifying each pack, its exact members, and its inherited
   product and disposition. Phase 5 applies that same list after confirming the source
   still matches. It makes no new classification decisions or search/model calls for
   detection. Running the same detection code twice could otherwise produce different
   boundaries; reusing the decisions also avoids paying for detection again. The cost
   is retaining the list and checking that it still matches the source.
2. **Validate preservation and completion.** A run passes only when existing behavior
   is preserved and every approved adoption has happened exactly as specified. A run
   that creates no packs must fail when packs were expected. The validator uses the
   original catalog, migrated catalog, and adoption list; unrelated records must remain
   unchanged, and there must be no unapproved packs or membership changes. This proves
   execution against the list, not whether its proposed boundaries make sense; those
   remain part of reviewing the rehearsal.
3. **Keep critical validation independent.** The migration uses application services;
   the validator independently reads and compares database state without calling the
   migration's membership or effective-decision helpers. A shared faulty helper could
   otherwise produce a wrong result and then declare it correct. Some small, focused
   duplication of the preservation and completion rules is accepted; existing reports
   can still explain differences.

Workshop concluded with this process accepted. Its apparent strengths are explicit
expected changes, independent checks, a rehearsed recovery path, and an adoption list
that serves execution, review, and validation. These are design judgments, not results
of verification. The workshop did not settle adoption scope, detection, or evidence
retention; the user settled those afterward (see the end of this document). Neither
authorized implementation.

## Constraints and inspected code

- Back up before opening the live catalog with application code. Inspected `db.py`:
  `session_scope()` upgrades by default; `readonly_connection()` uses SQLite
  `mode=ro`. Baseline reads must not trigger an upgrade.
- Inspected `commands/find_packs.py` and `find_packs/evidence.py`: `_visit()` skips
  folders with no unsettled files. Existing behavior cannot adopt the filed catalog.
- Inspected `membership.py`: joining deletes the file entry and its cascading
  evidence, analysis, errors, and review flags, and resets the member's disposition
  and subpath. Validation must compare effective decisions through the pack, rather
  than require all database rows to remain identical.
- Keep a working downgrade and the original backup. A downgrade preserves pack
  decisions as file decisions, but does not restore deleted per-file evidence;
  restoring the backup is needed for a complete rollback.
- Follow the project verification policy: behavior-level validation scripts, direct
  checks, and appropriate static checks; no new unit tests or unit-test tooling.
- Schema migration and adoption must not move library files. Placement differences
  must be explained and resolved before the live run.

Code paths above are under `apps/rpg-librarian/src/rpg_librarian/`. Reusable scripts
in `~/data/rpg_test_tools/` are documented in the handoff; they have not been inspected
or run in this planning session.

## Phase 1: back up the database

- [x] Establish that the catalog is not being changed during backup and rehearsal.
- [x] Create a raw copy and a consistent SQLite backup in
  `~/data/rpg-librarian/backups/`, following the entry-table cutover approach.
- [x] Record revision, integrity, row counts, and backup hashes without invoking
  an auto-migrating application command. Preserve the baseline separately from
  the working copy.
- [x] Capture baseline application reports, the unfiled worklist, and placement/dry-run
  behavior on a hashed copy of the verified backup with the `0005` code, as settled
  under decision 4 below. The original is never opened by application code.

**Outcome and verification:** readable, intact pre-migration backups and an immutable
baseline for all later comparisons. Verify the backups before developing or running
anything that writes to the catalog.

## Phase 2: build the post-migration validation script

- [x] Build a behavior-level comparison script accepting an original catalog, a
  migrated catalog, and an expected adoption list explicitly, with read-only access
  and no implicit upgrade. Establish effective product, disposition, and membership
  through independent database reads, without the migration's decision or membership
  helpers.
- [x] Implement the schema-only comparison from [checks.md](checks.md): original rows
  and column values unchanged, new pack references null, new tables empty, and expected
  revision/schema/integrity/foreign keys. Run it before detection or adoption writes.
- [x] Compare every file's identity, path, content metadata, duplicate relationships,
  and effective product and disposition. Compare computed destinations and pending
  moves using a baseline method that works at `0005` without modifying the original.
- [x] Check catalog integrity and foreign keys, file-entry versus pack membership,
  pack entries, and the one-kept-pack-per-product rule. Account for every file,
  including missing files and trash; distinguish intentional schema and adoption
  changes from unexplained differences.
- [x] Prove completion against the adoption list: every specified pack exists with
  exactly its specified members, product, and disposition; there are no unapproved
  packs or membership changes. Prove that records outside the expected changes are
  unchanged. A no-op migration fails when the list expects adoptions.
- [x] Report evidence, analysis, error, and review-flag changes according to the
  adoption policy settled before phase 3. A passing result cannot silently ignore
  those losses.
- [x] Derive permitted adoption differences by specific record and field from approved
  membership and the retention policy. Explicitly check new pack entries and detection
  records. Do not exclude whole tables; every unexplained difference fails.
- [x] Exercise the validator on unchanged data and deliberately altered disposable
  copies to show it detects lost files, changed decisions, placement changes, invalid
  membership, skipped adoptions, unexpected packs, and unrelated evidence loss. Emit
  reports that identify the checkpoint, affected record/field, and expected versus
  actual result, with a failing exit status for violations.

**Outcome and verification:** a validator built before the migration implementation,
with demonstrated ability to detect unsafe changes and incomplete adoption. Success
requires both preservation and completion.

## Phase 3: build the migration code

- [x] Settle adoption scope, detection strategy, and evidence retention policy (settled
  2026-10-03; see Settled design decisions below). Still to build: the adopt mode.
- [x] Implement the explicit migration entry point: apply existing schema migration
  `0006`, then adopt eligible filed folders with their shared product and disposition.
  Mixed folders remain loose; automatic duplicates remain outside packs.
- [x] Allow the schema-only checkpoint to run after upgrade and before proposal
  generation or adoption changes data. Only proceed when that comparison passes.
- [x] Separate proposing adoption from applying a fixed adoption list. Include exact
  membership and inherited decisions, explicit catalog selection, a source-match check,
  and safe rerun behavior. Application uses the existing services and must not make
  new classification decisions. If proposal generation uses search or a model, measure
  and limit its calls; preserve its decisions for rehearsal and live execution.
- [x] Check the implementation on disposable fixtures, including mixed decisions,
  duplicate exclusions, existing packs, and reruns. Run appropriate lint, format,
  type, and migration checks.

**Outcome and verification:** migration code ready for a full rehearsal, with its
effects described well enough for the phase-2 validator to judge them.

## Phase 4: run against a copy and validate against the original

- [x] Create a fresh working copy from the phase-1 baseline, upgrade the schema, and
  validate the schema-only result against the original. Retain the intermediate result
  before generating the adoption list and applying adoption using that list.
- [x] Run the phase-2 validator against the untouched original baseline and the
  adoption list. Review proposed pack boundaries, exact membership, skipped folders,
  evidence changes, placements, and processing costs. Fix the list after review and
  repeat application on a fresh copy if its decisions change.
- [x] After independent comparisons pass, run the application checks in
  [checks.md](checks.md): pack/product reports show expected membership and decisions,
  the unfiled worklist gains no artificial work, and `reorganize --dry-run` adds no
  moves or collisions. Account for existing pending/blocked files and expected report
  presentation changes. Do not run scan or enrichment for these checks.
- [x] Apply the same list again to verify it does not create additional packs or lose
  decisions. Rehearse downgrade on a separate migrated copy and backup restoration.
- [x] Resolve unexplained differences and repeat the rehearsal after any relevant fix.

**Outcome and verification:** a successful full-catalog rehearsal, comparison report,
and usable rollback procedure. Retain the original baseline, migrated copy, and final
reviewed adoption list. That exact list defines the expected live changes.

## Phase 5: run against the live database

- [x] Confirm the live catalog still matches the rehearsed baseline. If it changed,
  refresh the backup and repeat the rehearsal against that new state before cutover.
- [x] Run the same migration against `~/data/rpg-librarian/catalog.db`, applying the
  exact reviewed and validated adoption list from phase 4. Check schema-only
  preservation before applying adoption. Do not rerun detection or make new
  classification decisions.
- [x] Run the same independent validator against the backup and that adoption list
  immediately afterward, checking preservation and completion. Record the outcome,
  pack counts, exceptions, and rollback location. Restore the backup if validation
  fails.
- [x] Record completion and verification before resuming scan, enrich, or filing.

**Outcome and verification:** the live catalog uses the pack schema and the verified
adoption behavior, with its effective filing decisions and placements preserved.

## Settled design decisions

Agreed with the user on 2026-10-03, one at a time. Counts below come from a read-only
look at the live catalog that day, using an approximation of the gate; they are
orientation, not verified results. The live catalog had already moved since the
background handoff (49 unfiled files, all missing from disk, and 50 missing files in
total; inbox last scanned 2026-10-03 01:02), so phase 1 must take a fresh baseline.

### 1. Adoption scope

Every product folder under a product line is checked. The walk starts at each product
line folder and visits its child folders; it does not ask about type or line folders.
Files sitting flat in a line folder (about 11.6k single-file document products, and
about 348 asset single-file products in shared folders) are not folders and are never
candidates.

A folder can be adopted only if all of these hold:

1. It is in the library root. The inbox is excluded; normal `find-packs` covers it.
2. Every eligible file in it (present, not an automatic duplicate) is filed `keep` to
   one product. `discard`, `superseded`, and `duplicate` folders stay loose.
3. It is that product's own folder under `<type>/<line>/<product>/`, judged with the
   placement code's own path function (names are sanitized, so a string compare
   would miss, for example, `Darklives: …` vs `Darklives- …`).
4. It passes the existing media gate.

The pack root is the topmost folder the model accepts; its subfolders are members, not
separate packs. Mixed folders, missing files, trash, and automatic duplicates stay as
they are. Product type is not a filter. Review the type breakdown of the adoption list
in the rehearsal. Rough size: about 299 top-level folders holding about 11.3k files
qualify structurally, of which roughly 165 are the true asset products stored in their
own folder; about 2,400 document-heavy product folders are dropped by the gate.

### 2. Detection

No deterministic shortcut. Filed candidates go through the existing `find-packs` path:
gate, folder-name search (skipped for generic names), model judgment (`pack`,
`container`, or `no_packs`), then lossless formation, which records `mixed` and leaves
the folder loose if its files do not share one product and disposition. The only change
to detection is an adopt mode that treats a folder whose files are filed as a
candidate, instead of skipping it as settled, and starts the walk at the product line
folders. The gate stays: document-heavy folders never reach the model, by the user's
agreement. Not yet measured: the real search and model-call load. Measure it with
`--dry-run --limit` on a copy before committing. The detection output is the proposed
adoption list; the user reviews it in rehearsal.

### 3. Retention

Accept the deletion of adopted files' entry-keyed rows; carry nothing onto the pack.
Measured for the roughly 11.3k candidate files: 11,304 per-file Google rows (replaced
by the pack-level folder search that `find-packs` copies onto the pack entry), 531
DTRPG, 531 RPGGeek, 532 text-analysis rows, 0 errors, and 62 review flags, all
resolved. Rows keyed by the file itself (`file_text`, ISBN results, metadata tables)
are untouched. Reasons: a pack holds one row per evidence kind, so choosing which
member's row wins is arbitrary extra logic; the evidence is stale per-file lookups
from before packs existed; `enrich` can regenerate it.

Safeguard: a folder is not adopted if any member has an unresolved review flag or an
error row; it stays loose. Today that excludes nothing (0 open flags, 0 errors); it
protects open work if one appears before cutover. Everything deleted is recoverable
only from the phase-1 backup. The validator requires the deleted rows to equal exactly
the rows keyed to the adopted files' entries; any other loss fails. If the user later
wants resolved review-flag notes kept, write them as a plain export next to the backup,
not onto the pack.

### 4. Baseline method at `0005`

The original catalog is never opened with application code. Phase 1 makes the backups
with the SQLite backup API or a read-only connection. A working copy of the verified
backup is hashed, and the baseline is captured on that copy with the `0005` code, a
temporary `git worktree` of `5c8b268`: `snapshot_placements.py`, `snapshot_reports.py`,
`list-unfiled`, and `reorganize --dry-run` through `guarded_run.py`. Re-hash the copy
afterward to show nothing changed, and keep the outputs beside the backup as the
immutable baseline. After migration, run the same captures with the new code on the
rehearsal copy and compare with the existing compare tools; expected differences are
new pack presentation and old file-entry ids not surviving. If the live catalog
changes before cutover, refresh the backup and baseline (phase 5 already requires
this). Limits: HEAD excludes the user's uncommitted `clear_errors` work (matters only
if it changes a read path), and `reorganize --dry-run` reads the real library from a
copy, which `guarded_run` permits because a dry run moves nothing.

Next: begin phase 1 when implementation is requested.
