# Completed implementation

The user also requested quick cleanup as the first step of `process-batch.zsh`.
Both `scripts/process-batch.zsh` and
`/home/eriksalt/data/rpg-librarian/process-batch.zsh` now start with
`quick-dedupe --root /phinneas/rpg/inbox`. A guarded failure prints a message and
continues into the unchanged scan/find-packs/enrich/filing/reorganize/review sequence,
including when already-cataloged survivors make quick cleanup refuse the inbox.
For fresh duplicate-heavy batches this avoids duplicate extraction, but survivors
may be hashed twice, and mostly unique batches can take longer. Trash metadata and
the timing of moves differ from a full scan alone.

Both scripts passed `zsh -n` and have identical contents. Stub executables verified
all seven commands execute in order for preliminary exit statuses 0 and 1, even
with zsh's exit-on-error option enabled. No live library processing was performed.

`quick-dedupe --root PATH [--dry-run]` is available in the app CLI. The root must be
registered staging. Survivors receive no catalog rows, while duplicates receive
file/entry rows committed before immediate movement to the library's duplicate
trash. Size filtering avoids reading files with no possible match; SHA-256 is
streamed directly for candidates. Progress and summary report successful hashes,
bytes hashed, survivors, duplicates, moves, and errors. Errors return status 1.

The command reuses public `check_placement` and `apply_placement` helpers from
reorganize, preserving non-overwrite moves, verified cross-filesystem copying,
catalog updates, and move rollback if the update fails. Shared `PathAllocator`
supports incremental allocation with cached destination directory listings.
Shared duplicate ranking preserves the established pack/library preference.

An inbox-only duplicate has no cataloged original id. Quick cleanup excludes such
unlinked duplicates from known originals, preventing reruns from consuming the
uncataloged survivor. Normal scan now ranks these unlinked trash copies behind
the survivor and links them when it is cataloged. This targeted scan adjustment
is necessary for the later `process-batch.zsh` workflow. Other existing filing
decisions, rows, errors, and root scan timestamps are untouched by quick cleanup.

## Verification

Disposable catalog/library/inbox runs checked these behaviors directly, with no
new unit tests or tooling:

- Dry run previews duplicates with byte-identical database and unchanged content.
- Known catalog and discarded trash matches move, inbox repetitions retain one
  copy, and different same-size content remains unprocessed.
- Missing and stale catalog paths are not treated as available originals.
- Collision allocation respects case-insensitive occupied names without replacing.
- Unrelated pending decisions and reorganize errors are unchanged.
- Reruns retain the original of an inbox-only duplicate.
- Moving survivors into an unregistered holding folder leaves no source file rows.
- Normal scan extracts retained text and links its previously unlinked trash copy.
- Cataloged survivors, library roots, and unregistered roots are refused.
- Simulated move failures retain retryable duplicate rows and return nonzero;
  both known-original and inbox-only failures recover on rerun.
- Sources changed during hashing are not cataloged or moved.
- Simulated EXDEV exercises verified copying and source removal.
- Simulated catalog commit failure after moving rolls the move back, records an
  error, and recovers on rerun.
- The real CLI accepts catalog/root/dry-run options and executes successfully.
- Ordinary reorganize previews/applies a trash move and has an idempotent rerun.

The refactored `allocate_paths` was also compared against its previous implementation
over 80 deterministic scenarios with colliding names, existing paths, uncataloged
occupants, and preferred names; every result matched.

Checks passed: Ruff lint/format on all six changed/new Python modules, ty checks on
those modules, `git diff --check`, and the existing shared-tools public API/package
boundary tests (3 passed). The main temporary-library verification exercised 12
scenarios, with additional direct checks for catalog rollback, invalid roots, and
ordinary reorganize. The app currently has no existing unit tests to run.

No 100,000-file/network-share performance benchmark was run. Known original hashes
are trusted only while recorded size/mtime still match; existing catalog contents
should be scanned up to date before import. Cross-filesystem copying was exercised
by injecting EXDEV, rather than using a real remote share. The unrelated pre-existing
edit to the bundled `review-items/SKILL.md` was preserved.
