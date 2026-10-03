# Pack migration: accepted checks

Accepted in workshop on 2026-10-03. These checks support the [five-phase
process](plan.md): build the validator before the migration, rehearse on a database
copy, then apply the same reviewed adoption decisions to live data. No checks or
migration phases have run in this item.

## Inputs and independence

Use the untouched pre-migration baseline, the schema-only result, the adopted result,
and the approved adoption list. The list specifies each pack, its exact members, and
its inherited product and disposition. Phase 5 reuses the list after confirming the
live source still matches the rehearsed baseline; it does not repeat classification.

Critical validation reads database state independently, with read-only access and no
implicit schema upgrade. It must not use the migration's membership or effective-
decision helpers. Application checks supplement these independent comparisons.

## Checkpoint 1: schema upgrade only

Check immediately after `0005` → `0006`, before proposal generation or adoption writes
pack, search, or judgment data. This checkpoint remains within the five-phase process.

- Every original row and every existing column value survives unchanged, including
  IDs, timestamps, evidence, analysis, errors, and review flags. The Alembic revision
  change is expected and checked explicitly.
- New `file.pack_id` and `entry.pack_id` values are null. The new `pack`,
  `folder_search`, and `folder_judgment` tables are empty.
- The revision is `0006`; the expected tables, columns, indexes, and constraints exist.
  Database integrity and foreign-key checks pass.

`0006` rebuilds `entry` and `file`, so this comparison catches schema-stage data loss
before legitimate adoption changes could obscure it. The extra comparison pass and
retained intermediate result are accepted costs for locating failures precisely.

## Checkpoint 2: adoption preservation and completion

Compare the adopted database against the untouched original baseline and the approved
adoption list. Success requires both preservation and completion.

- Account for every original file, including missing files and trash. Preserve its
  identity, root and path, stored content metadata, duplicate relationships, effective
  product and disposition, and expected destination. A member's effective decision
  comes from its pack and the pack entry, independently established by the validator.
- Every approved pack exists with exactly its specified members, product, and
  disposition. No unapproved pack or membership change appears. A run that does
  nothing fails when the list expects adoptions.
- Check database integrity, foreign keys, valid entry types and references, the
  file-entry versus pack-membership rule, pack entries, and at most one kept pack per
  product. Automatic duplicates remain outside packs.
- Records outside the permitted changes remain unchanged.

### Permit differences by record and field

Derive permitted differences from exact approved membership and the settled retention
policy. Do not exempt entire tables from comparison. Every unexplained difference
fails validation.

Examples of expected changes for an adopted file:

| Record or field | Permitted change and condition |
|---|---|
| `file.pack_id` | References the specified pack. |
| `file.disposition` | Becomes `unfiled`; its effective disposition remains the original decision. |
| `file.subpath` | Unchanged (changed during implementation, 2026-10-03: the member keeps its stored subpath so its destination stays identical; see [progress.md](progress.md#phase-3-done-2026-10-03)). |
| The file's own `entry` | Is removed; the pack entry supplies the same effective product. |
| Rows keyed to the removed entry | May disappear only if the retention policy permits it, and only for that specific entry. |

New pack entries and detection records also need explicit checks. The retention policy
was settled on 2026-10-03 (see [plan.md](plan.md#settled-design-decisions)): deletion
of an adopted file's entry-keyed rows (evidence, text analysis, errors, review flags)
is accepted, with nothing carried onto the pack. So the validator requires the deleted
set to equal exactly the rows keyed to the adopted files' entries, and fails on any
other loss. Rows keyed by the file itself must survive. No adopted folder may have had
an unresolved review flag or an error row on a member. Detection records (settled with
the adopt mode): the target gets exactly one `folder_judgment` row per applied pack
(outcome `pack`, linked by `pack_id`, with the listed fingerprint) and, when the list
has a search, one `google_search_result` row on the pack entry equal to it. `folder_search`
stays empty; proposal answers and searches live only on the proposal copy.

This specificity catches, for example, accidental deletion of an unrelated file's
evidence. It adds detail to the comparison contract, which must be revised deliberately
if intended migration behavior changes.

## Checkpoint 3: application behavior on the rehearsal copy

After independent comparisons pass, exercise the application against the migrated copy
without running scan or enrichment:

- Pack and product reports expose adopted packs with expected members and filing
  decisions. Expected presentation changes are allowed; old file-entry IDs are not
  required to survive adoption.
- The unfiled worklist gains no artificial work from members' stored `unfiled`
  dispositions.
- `reorganize --dry-run` proposes no additional moves or collisions compared with the
  original baseline. Existing pending moves and blocked files remain accounted for;
  the migration is not required to repair them.

Capture baseline application outputs on a hashed copy of the verified backup with the
`0005` code (a `git worktree` of `5c8b268`), never on the original; the method is
settled in [plan.md](plan.md#settled-design-decisions). These
offline checks add evidence that correct database state is presented and placed
correctly, at the cost of capturing and comparing baseline behavior.

## Demonstrate the checks and recovery

Follow the existing plan to exercise the validator on unchanged data and deliberately
damaged disposable copies. Demonstrate rejection of missing files, changed decisions,
placement differences, skipped adoptions, unexpected or invalid membership/packs, and
unrelated evidence loss. Report the actual results, not just which cases were planned.
Use behavior-level scripts and direct checks; no new unit tests or unit-test tooling.

Reapply the same adoption list to check rerun safety. Rehearse downgrade on a separate
copy and restoration from backup. A downgrade preserves pack decisions as file
decisions but does not restore deleted per-file evidence; complete recovery requires
the original backup.

During live execution, retain the same schema checkpoint and independent preservation
and completion comparisons. If validation fails, follow the plan's backup-restoration
procedure before resuming processing.

## Workshop conclusion and remaining uncertainty

The accepted design covers schema losses, incorrect or incomplete adoption, unrelated
changes, and application regressions. Separate checkpoints and precise differences
should locate the failing operation and affected record. Direct database comparisons
plus a small offline application check appear proportionate to the migration.

These are judgments of the design, not demonstrated performance. Confidence must come
from exercising the checks against disposable copies. Comparisons prove execution
against the approved list; review of the rehearsal still determines whether proposed
pack boundaries make sense. Adoption scope, detection strategy, evidence retention, and
the baseline method were settled on 2026-10-03 in
[plan.md](plan.md#settled-design-decisions).
