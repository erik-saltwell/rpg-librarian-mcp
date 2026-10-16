# Sync registered sources: implementation plan and outcome

Implemented the owner-approved multi-source design. This supersedes the original
Brendan-only plan and its unresolved proposals. The original rubric in intent.md
is preserved; evidence is recorded in evaluations.md.

## General design

`sync-source` manages catalog-bound source definitions and reusable account profiles.
`sync-sources --catalog PATH --inbox ROOT [--source NAME ...]` attempts all enabled
sources in name order, or explicitly selected sources in argument order. OneDrive
is the first provider; multiple folders/accounts are supported. Google Drive and
Dropbox remain future adapters, not partially working options.

The provider interface owns complete observation, content-version validation and
verified downloads. Shared ingestion owns current-content classification by exact
SHA-256, a per-source whole-batch threshold (default 100), private staging, safe
publication, recovery and handoff to the existing process-batch runner. Namespaces
are provenance, not product lines. Remote deletions never remove local content.

Each source completes discovery/classification/copy/processing before the next
source starts. Existing scan/inbox and catalog-wide downstream scopes are retained;
leftover work can bleed into later runs, as approved. A catalog orchestration lock
covers the entire invocation, including its internally invoked batch runs.

Zero pending files exit quietly. An oversized source emails manual handling once
per unchanged pending manifest and publishes/processes nothing. Small batches are
journaled and staged completely before publication. Existing destination content
is never overwritten; updated versions can coexist under deterministic names.
Source failures do not stop other sources, and return nonzero. One combined failure
email is attempted after all sources; successful processing retains shared review
reporting without redundant per-source failure mail.

An explicitly recorded unfinished admission resumes before the quiet-source branch.
Processing-only recovery needs no provider sign-in or source access. Saved completed
batch receipts reconcile interrupted handoffs; known failed review mail retries
without repeating processing. Pending SMTP delivery after interruption becomes
unknown and is not blindly resent. Orphaned batch children are stopped under the
catalog lock before any new source work.

## Completed phases

- [x] Registry/provider boundary: `sync/registry.py`, `sync/providers.py`,
  `commands/sync_sources.py`, CLI registration, account reuse, enable/disable,
  auth/doctor/status, stable identity and legacy journal adoption. Source state
  supports validated names; historical rows and original journals are preserved.
- [x] Exact classification: `sync/ownership.py` indexes present catalog occurrences
  and uncataloged inbox candidates by size, verifies local bytes, and caches precise
  freshness signatures. `sync/ingestion.py` caches verified source SHA-256 by item
  and content version. Metadata guesses never establish ownership. Complete delta
  observation and old cursors reuse existing `imports/discovery.py` behind OneDrive.
- [x] Admission/publication: independent default 100-file gate; private bounded byte
  cache (20 GiB default); resumable immutable admitted manifests; whole-batch staging;
  no-replace publication and journaled per-file progress; stale partial cleanup;
  updated-version coexistence; incomplete observation and source mutation fail
  safely instead of publishing an unchecked prefix or reporting zero.
- [x] Shared pipeline integration: internal already-locked batch entry point,
  ingestion/batch receipt linkage, source provenance in filing context, serial runs,
  retained child cleanup and interruption codes. `import-run` is retired with
  actionable migration guidance; duplicate legacy processing is no longer active
  through that CLI. Historical status/review commands remain available.
- [x] Notifications/operations: shared SMTP transport, durable manual notices,
  source failure continuation, one combined final failure email, successful review
  reporting, failed-mail retry and explicit uncertain delivery state. Receipts retain
  source counts, manifests, verified/downloaded bytes, errors and sanitized frames.
- [x] Verification/documentation/production: controlled behavior checks below,
  lint/types/format/diff checks, updated READMEs and repository launcher, production
  backups and wrappers, private production source registry with Brendan adopted.
  No nightly scheduler was installed, live import run, real email sent or commit made.

## Verification performed

All checks used disposable catalogs/journals, controlled Graph operation boundaries,
an agent stand-in with actual MCP/catalog writes, real file copying and encrypted
loopback SMTP. No new unit tests or automated repository suite were added.

- `/tmp/check-sync-integration.py`: two serial source lifecycles; independent 101-file
  deferral while another source completes; 100-file admission; unchanged manifest
  suppression; manual hash matches; quiet repeated runs; preserved updated versions;
  multiple source failures and exactly one captured combined failure email; offline
  processing recovery; disabled/explicit selection; SMTP refusal.
- `/tmp/check-sync-recovery.py`: actual SIGKILL during publication and agent execution;
  overlapping-job rejection and orphan cleanup; interrupted discovery and expired
  cursor recovery; custom/zero thresholds; manual completion of deferred work;
  same-size/restored-mtime local edits invalidate hashes; cache budget failure/retry;
  source mutation during download; preserved legacy journal and offline handoff.
- `/tmp/check-sync-mail.py`: known failed review delivery retries the saved receipt
  without another batch run; actual SIGTERM returns 143 and resumes successfully.
- `/tmp/check-sync-cleanup.py`: abandoned partial download removal and interruption
  during final SMTP delivery records uncertainty without a second send attempt.
- `/tmp/check-batch-integration.py` rerun: the existing standalone pipeline still
  passes CLI/MCP/scan/placement, quiet/reporting, stage failure/signal, agent failure,
  partial-commit, recovery and SMTP refusal behavior checks.
- Ruff lint, formatting (148 application files), ty application checks and
  `git diff --check` passed.

A controlled two-source repeated idle run took 0.049 seconds, downloaded zero bytes
and started no batch. It hashed 303 local bytes once after their library placement;
this is small-fixture evidence, not a large-library/live-network runtime guarantee.
First reconciliation of old heuristic ownership can require significant hashing
and temporary downloads. Discovery/copy budgets retain progress across runs.

## Production handoff

Backups: `/home/eriksalt/data/rpg-librarian/backups/sync-sources-20261016T203325Z/`.
`process-brendan.zsh` selects Brendan using the staging root `/phinneas/rpg/inbox`;
new `sync-sources.zsh` runs all enabled sources. Both forward additional arguments.
`process-brendan-forever.zsh` exits with clear nightly migration guidance instead
of keeping the old five-minute loop. A private `imports/sources.json` adopts Brendan
identity while leaving its revision journal untouched until the next real sync.

Production wrappers were checked with a stand-in selected after shell startup and
masked loopback SMTP settings. No real CLI import/mail was invoked by those checks.
The legacy journal contains unfinished published work, which the first real run
will resume before fresh discovery. Read-only legacy inspection and registry
creation did not process those files. No live OneDrive or real Claude behavior was
claimed verified; those remain operational verification limitations.
