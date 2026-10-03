# Implementation progress

Approved policy is recorded in [item.md](item.md). Implementation covers basenames only: preserve folder structure and metadata names. Staging source paths remain accurate until library placement; all kept files, pack members, and trash destinations use the policy.

- Shared Unicode-aware filename sanitizer and case-insensitive suffix allocator implemented.
- Placement integrates the policy and persists cleaned/suffixed subpaths.
- `sanitize-filenames` previews filename-only production cleanup and provides explicit `--apply`, SQLite backup, per-file durable journal, source checks, and no-overwrite renames with rollback on catalog failure.
- Production cleanup applied: 2,666 filenames (2,386 loose kept files, 154 pack members, 126 trash files), including 3 collision suffixes. No blocked files or application errors. Folder structure, product assignments, and staging files were preserved.

## Verification

- Ruff lint and formatting, `uv run ty check`, wheel/source build, and `scripts/check_migrations.py` passed.
- Direct temporary-catalog rehearsals passed for preview/apply, byte preservation, backup/journal creation, repeated cleanup, Unicode and reserved Windows names, long stems with preserved extensions, stable suffixes, staging placement, persisted subpaths, disk-only case-insensitive collisions, pack/trash placement, and preservation of pending requested renames.
- A database trigger deliberately rejected an update in a temporary catalog: the failed cleanup restored the file's original disk name and catalog path.
- The production filesystem was checked directly for successful no-overwrite renames and refusal to replace an existing destination.
- Production verification against the backup preserved all 34,302 file rows and unchanged data in all 24 other tables. Only the planned file paths/subpaths and bookkeeping timestamps changed.
- All 2,666 renamed destinations exist, old names are absent, and file sizes/modified times are unchanged. SHA-256 content comparisons passed for 20 sampled files; full content hashing of the approximately 32 GB renamed was not performed (renames do not rewrite bytes).
- All 34,252 library filenames comply and library paths are unique under case-insensitive comparison. SQLite integrity and foreign-key checks passed.
- A second production cleanup preview reports **0 changes, 0 blocked**. No direct check on a Windows client was performed.
- Shared placement computation confirms 34,252 unique compliant destinations and **0 pending moves** after cleanup.

## Production artifacts

- [Applied rename list](/home/eriksalt/data/rpg-librarian/filename-cleanup-applied.json)
- [Post-cleanup preview](/home/eriksalt/data/rpg-librarian/filename-cleanup-after.json)
- [Database backup](/home/eriksalt/data/rpg-librarian/backups/catalog-before-filename-cleanup-20261003T222710848313Z.db)
- [Durable rename journal](/home/eriksalt/data/rpg-librarian/backups/catalog-before-filename-cleanup-20261003T222710848313Z.jsonl)

The backup alone does not undo physical renames; keep the journal with it for recovery. Implementation and production cleanup are complete; no commit or publication was requested.

Existing unrelated uncommitted work is being preserved. No unit tests are being added per project workflow.
