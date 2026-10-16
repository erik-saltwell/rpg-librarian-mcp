# Extract from Brendan — implementation handoff

The manual importer is implemented in the active app. The user will run it
repeatedly before returning for nightly scheduling. No timer was installed and
no Brendan RPG content was copied into the production inbox during verification.
Live content access was checked using only his root organizing catalog.

## Implemented behavior

- `import-source add/auth/doctor`, `import-run`, `import-status`, `import-reviews`,
  and `import-review resolve` are registered CLI commands.
- Source settings use the existing application `.env`; MSAL uses the existing
  private token cache and saves refreshed cache data atomically.
- The read-only Graph client checkpoints paginated baseline/delta discovery,
  retains folder ancestry, recovers expired cursors, and downloads through a
  separate request without forwarding Graph authorization to the storage host.
- Every top-level source folder is a durable complete transfer group. Selecting
  it queues every eligible missing descendant. Transfer limits may pause it
  across runs, but scanning, pack discovery, enrichment, filing and placement
  wait for its transfer barrier. Newly discovered additions reopen that barrier.
- Underscore-folder descendants and organizing/control files remain excluded.
  Ordinary underscore-prefixed files are allowed; nested remote shortcuts are not
  followed. Selected files and their ancestors are revalidated before download.
- Matching carries the approved metadata assumptions into production, including
  product-line associations, distinctive filenames/sizes and renamed PDF titles.
  Local size/mtime is checked before an ownership skip. Ambiguity imports without
  review. Changed remote revisions bypass the previous filename assumption and
  receive a byte check. Downloaded candidates receive SHA-256 comparisons.
- Publication refuses overwrites, journals hashes and destinations before rename,
  recovers publication after interruption, and retains source/content history.
  Ownership evidence includes original local filename, size/mtime and local hash.
- Targeted scan does not mark other files missing or update a complete-root scan
  timestamp. Pack discovery uses the complete group's imported file IDs.
  Enrichment and placement are scoped. A dedicated headless Claude session uses
  a private manifest; MCP enforces both selected entry IDs and complete member
  file scope and rejects other write tools.
- Persistent reviews, retry state, run summaries and conditional digest delivery
  are durable. No empty/success mail or unchanged review repeats. Failed mail
  retains a stable Message-ID for retry. Manual catalog review resolution can
  reopen a completed group's pending placement.

## Implementation choices that supersede the proposal

The importer uses a protected SQLite **journal beside the catalog** at
`imports/brendan.sqlite3`, rather than additive SQLModel/Alembic importer tables
inside the large catalog. Its own schema version, unique remote/revision keys,
queue indexes and transactional state changes are application-owned. Catalog
file references are logical, and the saved matching evidence survives catalog
cleaning. This keeps importer bookkeeping separate from normal catalog migration
and avoids coupling provenance deletion to catalog cleanup. Back up both databases.

The proven direct-ID delta integration is implemented. An unverified recursive
fallback and sharing-URL bootstrap were omitted: setup already resolved the
actual source IDs, and live baseline and incremental delta passed. Access failures
remain visible and retryable rather than silently selecting a different source.
Review export is JSON, suitable for the existing agent/CLI workflow. SMTP outbox
state is compact journal records rather than separate ORM delivery models.

Source renames update remote provenance without redownloading completed versions;
already published files retain their copied paths. Pack work is scoped by imported
file IDs so a renamed top-level folder cannot drop old copied paths from scope.
Source content remains subject to concurrent changes between observations; the
importer revalidates selected metadata/ancestors and content versions around a
transfer, then converges on later discovery cycles.

Run deadlines prevent starting new work after expiry. Existing scanner/provider
calls in flight can overrun that deadline. Interrupted content transfers restart;
range-resume is not implemented. A single oversized first file requires
`--allow-oversized` or a larger byte budget. Pending-byte status includes eligible
files whose ownership is not yet classified and is an upper bound.

## Verification performed

All scratch behavior checks were outside the repository; no new or expanded unit
tests or test tooling were added.

- Full live Graph discovery completed in the new importer against a scratch
  catalog: 36,194 remote observations and 31,306 eligible files in 386 top-level
  groups. A second live discovery completed from its terminal delta checkpoint.
  No RPG content transfers or emails occurred in those runs.
- The production Graph streaming client downloaded the 1,435,090-byte root
  `catalog.json` to temporary storage; JSON contained 7,476 records and the
  calculated SHA-256 had the expected format. No source writes occurred.
- `import-source doctor` passed cached Microsoft acquisition, shared-root
  metadata and delta access. Invoking it from `/tmp` through `uv --project`
  also passed, confirming source-location `.env` behavior for this checkout.
- Matching streamed the 383k-row live local catalog read-only in 2.64 seconds;
  peak process RSS was 136.5 MiB. It retained 22,226 filename candidates and
  12,339 relevant renamed-PDF candidates for 31,306 remote files. A spread
  sample of 60 previously likely-owned records passed the new matcher and local
  freshness checks. This is sample evidence, not a byte audit.
- Controlled local Graph fixtures passed bounded nested-folder transfer/resume,
  the no-processing-before-completion barrier, underscore ancestry/rename
  filtering, stale-local ownership rejection, SHA-256 duplicate skipping,
  collision-safe publication, changed-content revision separation, publication
  recovery without repeated download, interrupted page resume, cursor expiry,
  and remote-delete preservation of local content/provenance.
- Targeted scratch scanning preserved an unrelated inbox file's presence and
  left the root's full-scan timestamp untouched.
- A real Claude MCP filing session processed two generated scratch documents,
  stored catalog review decisions and completed the folder without interaction.
- Three generated token PNGs became one three-member pack through real model
  discovery, enrichment and a real headless filing session. Resolving its scratch
  review with a discard decision reopened placement and moved exactly those
  three members to the existing `.trash/discarded` location. An unrelated inbox
  file was preserved. The first scratch assertion used `discard` instead of the
  existing bucket name `discarded`; the verification expectation was corrected.
- Actual in-process MCP calls rejected an outside entry and a rename write while
  accepting a selected entry judgment.
- A local SMTP sink passed no-review/no-mail, new-review delivery, unchanged
  review silence, resolution/reopening, changed reason, and failed-send retry
  with the same Message-ID. Existing Gmail authentication and the previously
  user-requested/received test email remain the live mail evidence; this feature
  verification sent no additional production email.
- File-lock overlap and path escape rejection passed. Matching provenance was
  retained after deleting the referenced scratch catalog occurrence.
- Ruff lint/format, type checking, the three existing tests, Alembic schema check
  and application source/wheel builds passed.

## Manual operation and remaining rollout

From this checkout:

```bash
uv run rpg-librarian import-run brendan --catalog /home/eriksalt/data/rpg-librarian/catalog.db --inbox /phinneas/rpg/inbox/brendan
uv run rpg-librarian import-status brendan --catalog /home/eriksalt/data/rpg-librarian/catalog.db
```

Repeat the import command to continue. Defaults: 100 content-transfer attempts,
5 GiB reserved transfer bytes, two-hour deadline and 50 filing entries. A large
selected folder can remain unprocessed across several runs until all missing
files arrive. The [application instructions](../../apps/rpg-librarian/README.md#brendan-onedrive-importer)
explain discovery-only, one-folder selection, pacing, copying-only, processing-only,
review export/resolution and recovery. Existing credentials require no changes.

Next: user-led manual rollout on real RPG content. After that, configure the
approved host's user-systemd service/timer when the user returns and supplies the
exact nightly hour/timezone. Actual production filing quality, long-running
backlog behavior, refreshed tokens after expiry, and scheduled execution remain
rollout evidence to collect. Keep the private journal and cache across runs.
