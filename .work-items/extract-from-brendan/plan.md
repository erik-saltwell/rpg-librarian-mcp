# Extract from Brendan — completed manual implementation plan

Implement one resumable app command that copies missing RPG content from Brendan's
already-shared personal OneDrive into the existing inbox, preserves his hierarchy,
processes complete top-level folders for packs, and sends only newly actionable
review digests. The user authorized manual invocation first and deferred nightly
scheduling until after repeated manual runs.

Decision basis: [accepted idea](idea.md), [approved rubric](intent.md), and
[technical design](design.md). The original design describes proposals;
[implementation progress](progress.md) records the final architecture, deviations,
verification evidence and limits. This plan reflects the delivered manual scope.

- [x] Register importer commands and existing `.env` configuration; integrate
  silent MSAL acquisition and explicit device authorization, with private atomic
  token-cache persistence. Verify live source access and source-location config.
- [x] Implement read-only Graph metadata, paginated delta, content streaming and
  privacy-preserving failures. Verify a full live scratch baseline, a subsequent
  incremental cycle, and a bounded root-catalog download.
- [x] Add a private versioned SQLite journal beside the catalog for source,
  inventory, complete folder groups, unique content revisions, provenance,
  retries, runs, reviews and digest state. Enforce an exclusive importer lock.
- [x] Reconstruct source ancestry; exclude underscore-folder descendants, control
  files and remote shortcuts. Queue all eligible missing descendants of every
  selected top-level folder. Save partial transfers across repeated invocations.
- [x] Carry metadata ownership methods and evidence into the matcher, verify
  current local freshness before skipping, import uncertainty, and check
  downloaded candidates by SHA-256. Measure matching at the live catalog scale.
- [x] Publish through hidden same-filesystem temporary files and exclusive rename,
  revalidate source metadata/ancestry/content versions, preserve changed revisions,
  and recover interrupted publication without overwriting destinations.
- [x] Enforce the complete-group transfer barrier before all processing. Reuse
  targeted scan, file-ID-scoped pack discovery, selected-entry enrichment,
  restricted headless Claude/MCP filing and scoped placement. Verify a complete
  generated token pack and reject unrelated MCP mutations.
- [x] Reconcile source-linked reviews and persistent failures. Export unresolved
  reviews as JSON, resolve importer issues, and deliver only nonempty newly
  actionable digests with a durable SMTP outbox and stable retry Message-IDs.
- [x] Verify interruption/cursor recovery, nested transfer budgets, ownership and
  collision behavior, source deletions, retained provenance, locks, path safety,
  conditional/retry mail, manual review resolution and scoped placement in scratch
  catalogs. Run lint, format, types, existing tests, migrations and build checks.
- [x] Document manual use, progress/status meanings, recovery and limitations in
  both READMEs; preserve unrelated workspace edits and the interactive workflow.

## Deferred deployment

The user will run the app manually on the real backlog. No production RPG import,
nightly timer, commit, merge or deployment was performed during implementation.
Nightly scheduling is a later user-requested setup task using the same command.
The approved scheduler host and Gmail configuration are already available; the
exact nightly hour/timezone and production rollout observations remain to collect.
Do not recreate credentials or re-register a nested staging root for scheduling.
