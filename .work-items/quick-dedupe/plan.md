# Quick duplicate cleanup

The agreed workflow is a 100,000-file inbox containing mostly byte-identical copies
of known content. One command removes duplicates without metadata extraction,
OCR, enrichment, pack discovery, or general reconciliation. It also retains only
one copy of previously unknown content repeated within the dump. Cataloged trash
participates in matching. Survivors must remain uncataloged.

The command requires a registered staging root and refuses already-cataloged
nonduplicate survivors instead of promising they have no catalog references.
Duplicate rows from interrupted runs may be retried. Errors are reported with a
nonzero exit status; the user must resolve them before moving the survivors out.
For an uncataloged inbox winner, a duplicate's `duplicate_of_id` is null: creating
a winner row would violate the survivor guarantee. Its exact hash is recorded.

Existing code inspected: `commands/scan.py` (ranking, hash matching, skip rule),
`commands/reorganize.py` (source checking, verified copy, rollback and bookkeeping),
`services/placement.py`, `services/filename_policy.py`, `paths.py`, `entries.py`,
`infrastructure/walk.py`, and `__main__.py`.

- [x] Expose shared duplicate ranking, safe placement application, and incremental
  filename allocation without changing ordinary scan/reorganize behavior.
- [x] Implement size filtering, streaming hashes, conservative winner validation,
  duplicate-only catalog writes, immediate scoped moves, progress and dry run.
- [x] Register CLI options and document the holding-pen workflow and limitations.
- [x] Verify behavior using disposable catalogs: known and incoming duplicates,
  unique survivors, trash matching, reruns, collisions, failures and recovery,
  source constraints, and normal scanning of survivors. Run lint/type checks and
  relevant existing tests; add no unit tests or test tooling.

Record duplicate rows before moving. Reuse reorganize's checked move and catalog
rollback behavior; never invoke its whole-root execution or clear unrelated errors.
Size and modification time are checked around hashing and before moving. Known
winners must still exist with their recorded size/mtime; missing, stale, and offline
occurrences are not proof of a surviving copy. Network reads remain necessary for
hash candidates. Cross-filesystem trash moves copy and verify content.

- [x] Add quick cleanup as the first command in both repository and production
  `process-batch.zsh`. Continue with the existing normal scan if preliminary cleanup
  refuses cataloged survivors or fails, retaining the existing processing sequence.
  Check zsh syntax and command order using stub executables without running the live
  library processing or contacting agents.
