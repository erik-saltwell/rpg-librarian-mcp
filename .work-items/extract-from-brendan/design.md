# Extract from Brendan — technical design

The manual implementation is now delivered. [Progress and handoff](progress.md)
record the actual journal architecture, verified behavior, limits and the user's
manual-first rollout. Where the following proposal differs, that implementation
record takes precedence. Nightly scheduling is deferred at the user's request.

## Purpose and decision basis

Import RPG content missing from my library from Brendan's personal OneDrive folder, which is already shared with my Microsoft account. Copy into my inbox preserving his folder hierarchy, then use the library's existing processing pipeline. A large initial comparison becomes a durable backlog drained by the same job used for nightly discovery. Imports continue without review gates, and email is reserved for newly actionable reviews.

The accepted behavior and tradeoffs are in [idea.md](idea.md); the approved six-dimension [quality rubric](intent.md#quality-rubric) remains unchanged. This document proposes implementation choices. Local prerequisite checks and signed-in browser access were verified on 2026-10-10; see [preflight findings](preflight.md). Direct Graph access, first-page delta and a bounded catalog download are verified; importer behavior remains unverified.

## Existing architecture inspected

Implement in `apps/rpg-librarian`, the active application. The old `packages/rpg-librarian-mcp` application was removed during repository cleanup on 2026-10-10. Keep atomic remote operations in `packages/rpg-librarian-tools`, following its existing package boundary.

Relevant existing files, relative to the repository root:

- `apps/rpg-librarian/src/rpg_librarian/__main__.py`: argparse command registration and CLI logging.
- `config.py` and `db.py` in that package: explicit catalog path, environment loading, SQLite sessions and Alembic upgrades. Use these instead of the legacy application's fixed `.catalog` layout.
- `model/File.py`, `Root.py`, `ReviewFlag.py`, `Error.py`, and `Entry.py`: SHA-256 hashes and locations, registered staging roots, retained review history, transient per-stage errors, and file/pack entry identities.
- `commands/scan.py`: root-level walking, hashing and metadata/text extraction, automatic duplicate/move recognition, and per-file commits. A full-root scan marks absent files missing before processing. It returns zero even when individual files failed.
- `commands/quick_dedupe.py` and `services/duplicates.py`: size-filtered SHA-256 comparison, freshness checks, and stable original selection. Quick cleanup refuses an inbox containing ordinary cataloged files, so it cannot be the nightly importer for an inbox retaining unresolved reviews.
- `commands/enrich.py`: cached evidence and retryable source failures; currently catalog-wide, with a per-source limit but no root/entry selector. It also returns zero despite individual failures.
- `enrichment/queries.py`, `services/lists.py`, and `services/reports.py`: ancestor-folder search clues and folder-scoped worklists. Preserved folder context already has a path through processing.
- `commands/find_packs.py`, `commands/reorganize.py`, and `services/file_moves.py`: folder-aware packs, catalog-driven placement, and non-overwriting filesystem moves. Reorganization currently has no entry selector.
- `server/tools.py` and the bundled `resources/skills/process-batch/SKILL.md`: existing filing services and agent judgment flow. Open review flags are excluded from the normal worklist.
- `scripts/process-batch.zsh`: quick cleanup, scan, find-packs, enrich, `claude -p "/process-batch"`, reorganize, then interactive `claude "/review-items"`. It has hard-coded paths and cannot serve as the unattended job unchanged.
- `observability.py`, bundled Alembic migrations, and `scripts/check_migrations.py`: existing event logging and schema verification conventions.

Source was inspected. The root README was refreshed during the v1 cleanup and now describes the active application; the app README provides detailed processing behavior. The cleanup does not change this design's integration targets. Unrelated existing workspace changes must be preserved.

## Components and commands

Add an application-owned `imports/` package with source discovery, state reconciliation, matching, transfer, processing coordination, reviews, and notifications. Add a thin `rpg_librarian_tools.onedrive` client accepting an access token and explicit drive/item inputs; it owns individual Graph requests, pagination responses and streaming downloads, not persistent catalog state. Add MSAL to the application and explicitly declare any new HTTP dependency at the package that imports it.

Proposed CLI, all accepting the existing `--catalog` option:

- `import-source add brendan --inbox PATH --drive-id ID --item-id ID`: register source identity and a dedicated inbox subdirectory, reusing its existing staging root; alternatively accept a shared-folder URL when the setup probe can resolve it.
- `import-source auth brendan`: interactive one-time device authorization or reauthorization, using the user's Microsoft account.
- `import-source doctor brendan`: check cached authentication, shared-folder access, discovery capability, inbox/library reachability, disk space, headless filing readiness, and configured mail transport. No content import or test email by default.
- `import-run brendan`: discover changes, reconcile unfinished work, transfer and process bounded batches, update reviews, and send a nonempty digest.
- `import-run brendan --discover-only`: build/update the remote inventory and persistent queues without downloading or processing content. Discovery state changes are intentional; this is not a read-only dry run.
- `import-status brendan`: counts, backlog age, retry state, last run, resource totals and notification failures.
- `import-reviews brendan --out PATH`: export the complete unresolved source review list as a local HTML report; JSON is available for agents. Reports retain previously emailed items.
- `import-review resolve ID --note TEXT`: resolve importer-level reviews after corrective action. Catalog filing reviews continue to resolve through `update_product` and existing review tools.

Use named source subcommands without making a general connector framework. Operational run configuration belongs beside the catalog in `imports/brendan.toml`. Per user preference, OneDrive client ID, authority, scopes, remote drive/root IDs and token-cache path come from the existing ignored `.env`, with the `RPG_LIBRARIAN_ONEDRIVE_*` keys documented in `.env.example`. Token cache contents remain in a protected host-local file, updated atomically on refresh, not embedded in `.env` or stored on the content share. Scheduled execution must load the configured `.env` explicitly; existing environment variables take precedence. SMTP credentials can use the same private `.env` pattern. Store no credentials, full sharing URLs containing access keys, or preauthenticated download URLs in logs or exported reports.

## OneDrive access and discovery

Use delegated MSAL public-client authentication supporting personal Microsoft accounts. Setup runs device authorization once; nightly runs acquire tokens silently from a durable, atomically saved cache. If interactive sign-in is required, record one actionable source review and stop remote requests without opening a login prompt. Continue processing already downloaded content when local prerequisites remain available. Microsoft documents both device authorization and silent token refresh in [MSAL token acquisition](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens).

Address Brendan's actual drive and shared-folder item, not a shortcut's path in my own drive. Prefer explicit IDs with read permissions appropriate to the shared source, verified during setup. If resolving a sharing URL through the shares endpoint is necessary, document the additional consent before setup: that endpoint currently lists `Files.ReadWrite` as its least delegated permission, despite the importer making no remote writes. Do not promise a read-only OAuth scope for every setup path. [Shared-item API permissions](https://learn.microsoft.com/en-us/graph/api/shares-get?view=graph-rest-1.0)

Probe delta on the actual shared-folder target. Microsoft describes paginated change feeds with resumable links, expired-cursor recovery, item-ID tracking, and folder renames that do not enumerate descendants. Maintain folder parent/name records so descendant paths can be reconstructed. Persist each page's inventory updates and continuation link together; publish the next completed-cycle delta link only after the cycle is durable. Repeated items are upserted with their latest feed occurrence. These are integration requirements, not proof that this particular shared folder supports delta under my account. [Graph delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)

If shared-folder delta is unavailable with granted access, use a checkpointed recursive children inventory with complete reconciliation passes. This costs more metadata requests and does not offer delta's consistency guarantee during concurrent edits; converge over repeated passes and revalidate every selected file before download. Persist a folder queue and pagination links. Never mark unseen items removed until a full successful inventory pass finishes. A denied, throttled, or interrupted traversal is not evidence of deletion. Do not broaden access to Brendan's entire drive merely to obtain a change feed.

During the first completed baseline, observed files are backlog. Later new identities and changed content are fresh work. If baseline enumeration spans runs, finish it before claiming this distinction is precise; files created during baseline can initially count as backlog. Later re-enumeration after cursor expiry preserves the original classification and import history.

Derive source-relative paths by walking stored parent IDs to the configured shared root. Ignore items outside that ancestry, source exclusions, and non-downloadable items. Exclude every folder whose name starts with `_` and all descendants at any depth. Prune recursive listing at excluded folders and apply ancestry filtering to delta observations. Recompute descendant eligibility after parent moves/renames; moving into an excluded subtree cancels pending imports without deleting local copies, while moving out makes unfinished eligible content discoverable. Resolve unknown ancestry before transfer. Initially support ordinary catalogable files, with PDFs as the primary use case and include/exclude rules for unwanted material; do not assume the share contains only PDFs. Nested shortcuts to other drives are excluded and reported in status rather than followed implicitly.

## Persistent state

Use additive tables in the existing catalog, with an Alembic migration after the current head. Proposed logical records:

- **ImportSource:** name, drive/root item IDs, staging `root_id`, inbox-relative prefix, discovery mode, baseline completion, cursor/continuation, inventory generation, enabled state and configuration reference. Folders awaiting traversal are stored as durable discovery work records when using recursive inventory.
- **RemoteItem:** unique `(source_id, drive_id, item_id)`, parent ID, name, kind, current remote path, last observed eTag/cTag, size, available remote hashes, first/last observation, baseline/fresh classification, and remote presence. Include folder records for path reconstruction.
- **ImportRevision:** remote item, local revision number, observed remote tokens, size, calculated SHA-256, source path at discovery/import, candidate destination, temporary path, transfer/processing stages, retry counts/deadlines, and completion timestamps. A nullable `file_id` links the actual catalog occurrence; a separate nullable matching-file reference records already-owned content. Both use `ON DELETE SET NULL`. Keep hashes and source history when catalog trash is cleaned. Unique revision keys and conditional state transitions prevent duplicate active work for the same observed version.
- **ImportRun:** start/end, source, outcome, active work IDs, stage totals, resource usage, stop reason, and durable processing-session scope. A host-level exclusive source/catalog job lock prevents overlapping importer runs; release is automatic on process death.
- **ImportReview:** source/revision or source-level subject, stable reason category, human explanation/action, catalog review/error references where available, semantic fingerprint, lifecycle revision, first/last observation, and resolution. Enforce at most one open issue per subject/category. Entry-less failures can live here before a file is cataloged.
- **ImportDigest and deliveries:** pending/sent/failed envelope with a stable Message-ID, captured `(review_id, lifecycle_revision, fingerprint)` members, attempt details and accepted-send time. Membership and delivery records provide a durable notification outbox.

Keep catalog disposition, pack membership, product assignment, `ReviewFlag`, and `Error` authoritative for normal library behavior. Import stages track coordination, not a second product/disposition system. Review state is independent of transfer state: an open review does not put a revision into a blocked-download stage. Resolve catalog file identity to its current entry or pack dynamically; entry IDs can change when pack membership changes.

## Matching and provenance

Use metadata-first comparison before downloading RPG content. The user accepts product-line/filename matching to skip likely-owned files, replacing the earlier requirement to download every unverified remote file for SHA-256 comparison. Normalize names conservatively, preserve edition/version distinctions, map source product lines through local names/aliases, and retain the match method and local evidence in provenance. Filename matches are assumptions of ownership, not proof of byte equality. Uncertain/ambiguous matches and conflicting size evidence remain download candidates without review gates. Compatible catalog hashes, if later available, take precedence; downloaded candidates still receive SHA-256 duplicate checks against present, fresh local occurrences.

Brendan's root `catalog.json` was inspected and downloaded during [preflight](preflight.md). Its 7,476 records include filenames, product-line `system`, title, group, type and rounded size_mb, but no hashes or full paths. It is dated June 2026 and cannot alone establish current remote completeness. Use it to seed comparisons and filing context; use current Graph metadata to discover later additions, resolve paths and enforce exclusions. Product-line/filename combinations are not unique in this catalog. Rounded MB values cannot establish exact size equality. Control files such as the source catalog are importer inputs, not RPG content to publish into the inbox.

This approach avoids downloading likely-owned overlapping content; only selected candidates are transferred within run limits. It accepts the possibility of missing a same-name revision. Persist remote identity/version observations where available so later changes can be reconsidered instead of making a name-based skip permanent.

Remember `(drive_id, item_id)` independently of path. A rename or folder move with unchanged content tokens updates observed provenance without repeating a completed import. When cTag is missing, fetch item metadata as needed; an eTag-only change does not conclusively establish changed bytes, so a conservative verification download may be necessary. Store both current remote location and the historical location used for each copy. Changed bytes create a new revision and never overwrite an existing local file or silently supersede a product. Cross-drive moves may acquire a different identity; SHA-256 matching handles the resulting new observation.

Remote deletions or moves outside the selected share stop pending remote transfers but never delete local copies. Completed revision history prevents routine reimport even after a catalog trash record is deleted; intentional reimport is an explicit future operation. A manually missing local copy is surfaced as an actionable review, not silently redownloaded forever.

## Transfer and crash recovery

Reuse the existing `/phinneas/rpg/inbox` staging root (currently catalog root 2) with importer-owned prefix `brendan/`. Publish as `inbox/brendan/Game/Publisher/Product/book.pdf`. Existing add-source rejects overlapping/nested roots, so do not register the subdirectory separately. Persist root identity and prefix, and constrain processing by imported file IDs and provenance. Supply original source-relative ancestors to enrichment/worklists so the synthetic `brendan` prefix does not become the first organizing clue. Preserve the complete hierarchy in the inbox; final library placement continues to follow existing product/subpath rules.

Download into hidden `.imports-partial/` under the importer-owned inbox subdirectory, so incomplete content is on the destination filesystem and excluded from normal scanning. Persist the chosen temporary and destination paths before transfer. Validate path components, reject traversal/absolute paths and symlink escapes, and apply reversible recorded mappings only when destination filesystem restrictions require them. Record original source names. For collisions or revised content, allocate a stable non-overwriting filename suffix within the same source-relative folder.

Use Graph `/content` to obtain a fresh download location and stream bytes. Its redirect is a short-lived preauthenticated URL; follow it without forwarding Graph authorization credentials and never persist it as a durable locator. Check size, calculate SHA-256, and re-fetch source version metadata before publication. If the source changed during transfer, discard/retry that attempted snapshot rather than record it as a completed version. [Download API](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)

Before publishing, recheck exact local matches and destination occupancy. Persist verified bytes/hash and planned destination, then use existing non-replacing movement semantics and commit publication. Filesystem movement and SQLite commit are not jointly atomic: on restart inspect both recorded paths and verify their hashes before adopting or retrying. Never infer successful publication solely from a missing temporary file. Reconcile published-but-uncataloged copies by recorded path; after scan resolve them by file ID and hash, then follow that ID through reorganization. Restrict recovery of a moved occurrence to linked scope and verified matches, not an arbitrary same-name file.

Initial implementation restarts an interrupted single-file transfer; optional HTTP range resume is deferred. Download byte accounting includes comparisons, retries and duplicates, not just retained files.

## Scheduling and bounded processing

Use one CLI invocation under a host scheduler, with an example Linux user systemd timer for nightly execution. The user approved this machine and its systemd user timer during preflight; exact hour/timezone remain to be confirmed. Manual invocation uses the same path and state. No scheduler is installed by this design task.

Proposed configurable starting limits: two-hour run deadline, 5 GiB remote download budget, 100 completed transfer attempts, and 50 filing entries per run. These are operational defaults to tune after observation, not rubric thresholds. Separate discovery request/time allowance from transfer and processing allowances so metadata enumeration cannot indefinitely consume the entire run. For delta, process only complete observation cycles; restart safely from durable continuations.

Select fresh items first, then eligible retries and oldest backlog. Within each class use stable ordering; avoid launching work that cannot fit the remaining budget. Large files receive a dedicated oversized-item allowance on a later run so they cannot be skipped forever. Processing can continue after transfer budgets are exhausted, and previous copied work is eligible even when remote discovery fails. Backlog starvation is visible through age/count metrics; a reserved backlog share is a later tuning option if sustained arrivals prevent catch-up.

The headless processing sequence is:

1. Reconcile published revisions and select bounded new/unfinished local work.
2. Scan selected files using existing extraction and duplicate/move logic. Add a partial-scan service entry point that does not mark unselected files missing or claim a complete root scan. Only a successful complete enumeration may perform root-wide missing reconciliation.
3. Run folder-aware pack discovery when applicable. Select complete eligible sibling/folder groups; do not create a pack from an arbitrarily truncated downloaded set. Defer pack formation for a known incomplete source folder while allowing loose-file scan and other folders to proceed.
4. Enrich selected entries and their pack context using existing evidence caches. Add scoped selection to enrichment rather than running catalog-wide enrichment every night.
5. Invoke a headless filing adapter, initially wrapping the existing `claude -p` pattern with explicit catalog, project working directory, bounded entry/folder scope, timeout and captured result. Launch by argument array, not shell interpolation. Verify installed CLI authorization and MCP readiness during setup; a read-only headless MCP call succeeded in a scratch catalog during preflight, but actual filing and scheduler-environment execution remain unverified. Use explicit MCP configuration and a narrow tool allowlist; CLI safe mode disables MCP customization and is unsuitable here.
6. Reorganize decisions from this scope using existing placement and non-overwriting movement. Resolve and record final catalog identities/paths.
7. Reconcile remaining review flags and persistent errors, export the full source review list, and consider a digest.

Provide an unattended filing instruction variant. The current skill can stop for user approval if evidence is absent; the variant must record an actionable review and continue to the next item instead. It never opens interactive review, requests input, or retries unchanged flagged entries each night. Existing interactive skills remain available for later manual review.

The current catalog has 383,348 file rows. Use indexed, paginated SQL selection; do not materialize the full catalog or all unfiled items nightly. Measure bounded queries and memory at this scale during implementation. Add run-scoped selection to processing services, and enforce mutation scope in the headless MCP session, not only in the prompt. Catalog vocabulary/product lookups remain readable across the library; entry filing, error clearing, pack operations and file renaming are restricted to the allowed work set. Permit narrowly identified related pack members when a complete pack needs processing. Existing kept files sharing an affected product may need placement adjustments; compute that dependency closure explicitly rather than running unscoped reorganization. Agent success is judged from committed catalog outcomes and unresolved scoped entries, not merely process exit status.

Keep SQLite transactions short around state changes and never hold one across remote transfer or agent execution. Sequential stage execution and an importer job lock prevent competing importer writers; refuse conflicting simultaneous importer sessions. Existing manual writers are not globally locked by this feature: use version/freshness checks to detect intervening edits, and report conflicts rather than overwrite them.

## Failures, review and email

Record item-specific failures without aborting independent items. Proposed retry schedule: after 5 minutes, 30 minutes, then 2 hours, with jitter; nightly runs pick up eligible retries. Promote repeated unchanged failures to one persistent actionable review after three eligible failed attempts, and continue automatic retries where useful. Authentication/permission failures requiring intervention are immediately actionable. Honor Graph `Retry-After` on throttling; if the wait exceeds the run deadline, persist the next attempt time and finish other local work. [Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling)

Source-level outages do not produce one review per file. A temporary outage remains status/log information; lost access or reauthorization creates one source-level review. If the source is unavailable, do not mark remote items deleted or local items missing. Fatal catalog or unavailable destination errors stop unsafe stages while retaining their queues.

Gather reviews only attributable to this source: imported file/pack review flags, persistent scan/enrichment/reorganization issues, unresolved mixed-pack judgments relevant to imported content, source access problems and importer failures. Unflagged unfiled items are not automatically review items; finish their normal processing first. If a filing session leaves selected entries untouched, persist unfinished work and promote repeated non-progress rather than declare completion. Exact automatic duplicates are not reviews.

A semantic fingerprint includes subject/revision, reason category, meaningful explanation, proposed action and relevant evidence. Exclude retry count, timestamps and formatting so nightly repetition does not manufacture change. Resolution followed by reopening increments the lifecycle revision; it is newly actionable even if the reason text is identical. Normalize existing catalog flags/errors into importer review records without moving their authority away from the catalog. Manual catalog resolutions are reconciled on the next job or review-export refresh.

Send one digest only when an unresolved actionable review has a lifecycle/fingerprint not successfully delivered. Immediately before sending, remove reviews that have resolved; if none remain, do not send. Include concise reasons/actions, source-relative paths, catalog IDs where present, totals, and a locator for the complete persistent review report. Do not email success reports or empty digests. Previously delivered unchanged reviews stay in the report without repeated emails.

Use SMTP with explicit TLS and environment-backed credentials as the first mail adapter. The user approved Gmail SMTP during preflight; use `smtp.gmail.com:465` with certificate-verified TLS and an app password when the account supports it. Private sender/app-password/recipient settings are populated in `.env`, and certificate-verified SMTP authentication passed during preflight. Delivery and the implemented digest adapter remain to be verified. No Microsoft mail permission is needed. Persist a digest before sending and mark it accepted only after SMTP acceptance. Retry a failed envelope with the same Message-ID; a newer run merges unsent actionable changes rather than delivering stale empty notifications. SMTP cannot guarantee exactly-once delivery if the process crashes after acceptance but before committing its delivery record; an occasional duplicate is preferable to silently losing a review. Notification failures retain the outbox and appear in status/nonzero run outcome without recursively generating email reviews about email failure.

Exit outcomes: zero when the bounded run completes with work safely queued or user reviews pending; nonzero for shared operational failures or notification delivery failure. Item retry counts/errors are in durable state and structured summaries. Existing stage return codes alone are insufficient because scan/enrich can return zero with errors.

## Observable acceptance behavior

- Repeated unchanged nightly runs produce no repeated downloads, filing decisions or digest emails.
- Renaming a source file or parent folder updates provenance without reimport when content is unchanged; modified content is handled as a distinct revision.
- Likely-owned content can be skipped by product-line/filename evidence without downloading; the recorded match method distinguishes assumptions from verified SHA-256 equality. Ambiguous matches can import without approval.
- Published content has Brendan's hierarchy under the dedicated inbox subdirectory; folder clues reach current enrichment/worklist behavior.
- Underscore-prefixed folders and their complete subtrees are excluded, including delta-only descendants and parent moves.
- Fresh work precedes baseline backlog, run limits persist unfinished work, and oversized items have a path to eventual execution.
- Crashes during discovery, transfer, publication, scan, filing, placement and mail preserve enough state to resume without overwriting files or forgetting work.
- A corrupt file or expired remote URL does not prevent independent items from progressing. Source authentication failure still permits local processing when possible.
- Existing and importer-level reviews remain accessible. Only newly actionable unresolved review versions are emailed; resolution and reopening behaves correctly.
- Catalog cleaning or reorganization does not erase provenance, and manual edits or unavailable paths do not silently suppress content or cause remote deletions to propagate locally.

## Remaining integration checks

Personal OneDrive, existing sharing, signed-in browser access, underscore exclusions, Gmail SMTP and this scheduler host are confirmed. Local catalog/storage, non-overwriting placement, user-systemd capability, headless read-only MCP and SMTP TLS passed [preflight](preflight.md). Microsoft client registration/authorization, cached silent acquisition, source IDs, direct listing, a first delta page and catalog download now pass. Complete baseline/incremental discovery, refresh after token expiry, current source volume, email delivery, exact nightly time and end-to-end scheduler filing remain pending. Existing folder clues are confirmed in source; their end-to-end quality on Brendan's real examples remains unassessed. Metadata-first matching reduces baseline bandwidth; candidate counts and runtime limits still need measurement. These checks are implementation/deployment dependencies, not reasons to redesign the accepted unattended workflow.

## Implementation scope update — 2026-10-10

The user authorized implementation for manual runs, with nightly scheduling deferred until after repeated manual use. Top-level source folders are durable transfer groups: once selected, queue every eligible missing descendant, finish that group over as many bounded runs as necessary, and only then scan/find packs/enrich/file/place it. Do not feed a partial transfer group into pack discovery. Already-owned files need not be copied. Underscore-folder and organizing-file exclusions remain applicable. A later discovery of additions reopens the folder transfer barrier.
