# Completed implementation

`clean [--catalog PATH] [--dry-run]` empties the library's three established trash
buckets, deletes file rows and cascading entry/metadata/evidence/error/review rows,
removes empty packs with their linked folder judgments, and compacts SQLite with
VACUUM. It includes uncataloged and hidden bucket contents and records of already
absent trash files. Products, product lines, roots, staging trash, unknown buckets,
and unrelated content remain. Kept files and kept pack members awaiting movement
out of trash are blocked and retained. Linked bucket/trash roots are refused;
links inside buckets are unlinked without traversing their targets.

Filesystem deletions precede catalog writes. Writer-locked batches of 256 commit
successful deletions; failed unlinks retain their rows. A failed catalog commit can
leave rows for absent files, which the next run reconciles. Surviving automatic
duplicates of removed originals are returned to unfiled, with their reference and
hash cleared to force metadata extraction on the next scan. Explicit decisions
on surviving files are preserved. File changes after enumeration are reported.
Failures return status 1, including failed compaction after committed cleanup.

The CLI is available through the existing editable installation; no new dependency,
schema migration, build, or installation step is needed. No real library trash was
deleted during implementation.

## Verification

Disposable-library direct execution covered 13 scenarios, plus an additional
compaction-failure check:

- Dry run preserves the database byte-for-byte and all content.
- All three buckets are cleaned, including uncataloged hidden files and missing
  catalog paths; empty bucket directories are removed.
- Dependent metadata, text, analysis, entries, flags and errors cascade correctly.
- Empty packs, pack entries, evidence and linked judgments are removed.
- Surviving duplicates become unfiled and receive extraction during a later scan.
- Kept files and kept pack members remain on disk and in the catalog.
- Other library files, staging trash and unknown buckets remain.
- Nested file/directory links are removed without changing external targets;
  symlinked bucket roots are refused before mutation.
- Unlink failures preserve rows and recover on rerun.
- Simulated catalog commit failure after unlink is reconciled by rerunning.
- A 300-file fixture verifies multiple committed batches.
- SQLite VACUUM reduces a metadata-heavy catalog; foreign-key integrity holds.
- Rerunning after successful cleanup does nothing except compaction.
- The real CLI accepts catalog/dry-run options and previews successfully.
- Simulated compaction failure returns nonzero while retaining committed cleanup;
  a subsequent run compacts successfully.

Ruff lint/format checks, ty checks on the changed Python modules, and
`git diff --check` passed. No new unit tests or tooling were added. The app has no
existing unit tests. No remote-share or 100,000-file benchmark was performed.

Usage and permanent-deletion/recovery behavior are documented in the app README.
Cleaning removes remembered hashes and decisions, so discarded content can be
rediscovered by subsequent imports. VACUUM requires rewrite space and can fail
while other database operations hold locks; committed cleanup remains valid.
