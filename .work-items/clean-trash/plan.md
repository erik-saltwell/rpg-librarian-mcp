# Clean trash and compact catalog

Clean the three existing library trash buckets, including uncataloged contents
and catalog rows for files already absent on disk. Leave other library/staging
content and unknown trash buckets alone. Kept files/packs awaiting movement out
of trash must be preserved and reported. Preview through `--dry-run`; ordinary
`clean` performs deletion without an interactive confirmation.

Delete filesystem objects before their rows, committing catalog cleanup in batches.
Failures retain their rows; if catalog cleanup fails after unlink, rerunning
reconciles the absent files. Do not follow symlinks. Cascade file/entry metadata,
delete packs after their last member is removed, and release surviving automatic
duplicates of removed originals to unfiled so they cannot be trashed as a last copy.
Keep products, product lines, roots and unrelated judgments. Compact SQLite with
VACUUM after the catalog transaction closes. Cleaning forgets discarded hashes.

Inspected: `paths.py`, `db.py`, model foreign keys and migrations, `membership.py`,
`commands/reorganize.py`, `commands/quick_dedupe.py`, CLI registration, and README.

- [x] Implement trash enumeration, scoped deletions, cascading catalog cleanup,
  partial failure reporting, SQLite compaction, and CLI options.
- [x] Document permanent deletion, scope, recovery, and forgetting content hashes.
- [x] Verify using disposable libraries: all buckets, dependent metadata, missing
  rows, packs, kept items, surviving duplicate references, uncataloged content,
  symlinks, partial failures, reruns, compaction and real CLI dry-run. Run lint and
  type checks; do not add unit tests or tooling.
