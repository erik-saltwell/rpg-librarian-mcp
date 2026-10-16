# Implementation completion

The process-batch CLI is implemented and verified. The work item is complete.

```sh
rpg-librarian process-batch --catalog /path/to/catalog.db --root /path/to/inbox
```

The existing production `~/data/rpg-librarian/process-batch.zsh` now forwards to
this command with its production catalog and usual inbox as defaults. Explicit
flags override the defaults. It no longer launches interactive review.

## Delivered behavior

- Catalog-wide review counts and paginated MCP identities come from the same
  snapshot-based `services/review_backlog.py` collector. It covers all four review
  queues, collapses linked organization-marker flags, preserves unrelated flag
  questions, and deduplicates entries with both flags and blocked moves.
- The parent orchestrator inventories new/changed input before quick deduplication,
  saves private atomic receipts under `logs/process-batch/<run-id>/summary.json`,
  and runs processing stages in subprocesses with structured metrics and private
  logs. A stage's zero exit code does not hide recorded file/source failures.
- Deduplication, scanning and pack discovery target the registered staging root;
  enrichment, filing, reorganization and review counts remain catalog-wide.
- Generic unattended filing supplies the bundled instructions and explicit
  catalog-bound MCP configuration to Claude. It includes image and pack tools,
  removes inherited Brendan manifest restrictions, and checks the remaining
  unflagged worklist rather than trusting a textual completion claim.
- Email follows the accepted quiet-run rules. Unknown input or backlog remains
  unknown; delivery failure is retained separately from processing results.
- Safe reruns preserve committed work. Batch-mode quick deduplication skips already
  cataloged survivors instead of treating their presence as an error; standalone
  quick-dedupe behavior is unchanged. Extraction retries are counted separately
  from new/changed input. Subsequent stages rely on existing catalog eligibility.
- Batch jobs and Brendan imports share a cooperative orchestration lock. Owned
  stage/agent process groups are cleaned up on termination; recovery stops abandoned
  children using their inherited run token before proceeding. Incomplete receipts
  are marked interrupted. Interrupted SMTP delivery remains unknown, not replayed.
- SMTP transport is shared with Brendan without changing Brendan's digest policy.
  Source documentation, MCP server instructions, both filing/review skills, and
  production copies for Claude/Codex/Gemini are updated. No new dependencies or
  catalog schema migration were needed.

## Verification performed

Behavior checks used disposable catalogs, controlled Claude/lookup stand-ins,
actual CLI child processes, actual MCP stdio/image results, actual scanning and
placement, and an encrypted loopback SMTP capture server. No repository test suite
or unit tests were created. Temporary verification scripts were outside the repo.

- `/tmp/check-batch-integration.py`: complete processing and a second no-new-input
  run; old backlog suppression and new-input notification with unchanged backlog;
  fatal enrichment and safe retry; deliberate scan-child SIGSEGV; dedupe fallback;
  invalid agent JSON, explicit agent failure, unfinished work, and partial committed
  filing followed by rerun; SMTP recipient refusal. All final scenarios passed.
- `/tmp/check-batch-recovery.py`: unknown input enumeration, cooperative batch and
  Brendan lock contention, SIGTERM with partially committed agent work, parent
  SIGKILL with orphan cleanup on the next run, and preservation/completion of the
  pending move. Both interruption modes and subsequent reruns passed.
- `/tmp/check-batch-extra.py`: handled per-source errors despite stage exit zero,
  real corrupted-PDF extraction with unchanged retry/no-new-input suppression,
  unavailable backlog represented as unknown, and Brendan delivery followed by
  suppression of the unchanged digest. Passed.
- `/tmp/check-batch-scope.py`: existing pending work in a second staging root was
  filed and moved while the scan targeted the requested root; changed cataloged
  input qualified for email. Passed.
- `/tmp/check-review-backlog.py`: four queues, overlapping entry reasons,
  organization markers with unrelated text, missing/resolved exclusions, finding
  members whose identities became a pack, and 519 distinct backlog items traversed
  through MCP pagination. Passed before and after the collector optimization.
- Both shell wrappers passed syntax checks and an isolated forwarding/exit-status
  check, including explicit catalog/root overrides and execution from another cwd.
- A read-only production collector call succeeded against the existing catalog
  (750 review items at the time, about 0.01 seconds). No production content processing
  was performed by that check.
- Final checks: `.venv/bin/ruff check apps/rpg-librarian/src/rpg_librarian`,
  `.venv/bin/ruff format --check apps/rpg-librarian/src/rpg_librarian`,
  `.venv/bin/ty check apps/rpg-librarian/src/rpg_librarian`, and `git diff --check`
  passed. Six production skill copies were checked byte-for-byte against source.

The first integration attempt exposed standalone quick-dedupe's refusal of
cataloged survivors on reruns. Batch-only filtering corrected that behavior; the
subsequent complete integration sequence passed. No existing tests were removed.

## Production updates and verification incident

Previous production launcher and skill copies were backed up under:
`~/data/rpg-librarian/backups/process-batch-cli-20261016T172856Z/`.
Production's executable still resolves to this checkout's editable virtualenv.
The Brendan launcher was left unchanged. New agent/MCP sessions discover the shared
backlog tool; the CLI supplies its own bundled filing instructions directly.

During the first wrapper smoke check, zsh initialization replaced the stand-in PATH,
so the real executable ran and sent one real failure email through configured SMTP
for the nonexistent `/tmp/chosen.db`. Its receipt confirms that all processing
stages were skipped because the catalog did not exist; no production catalog or
content was processed. This was disclosed to the owner. The corrected check sets
PATH after shell initialization, masks SMTP with a loopback refusal destination,
and passed for both wrappers without invoking the real application.

## Limits

No live Claude/model or external lookup run was performed; those boundaries were
controlled during verification. The real CLI/MCP transport, catalog writes, image
results, file moves and encrypted SMTP transport were exercised locally.
The first version accepts registered staging roots, not arbitrary descendants.
New/changed size/mtime qualifies as new input; unchanged extraction retries do not.
A parent/machine failure can prevent immediate final reporting. Run-token orphan
recovery uses Linux `/proc`; the production environment and checks were Linux.
Other standalone mutating commands and interactive MCP writes do not participate
in the cooperative orchestration lock. SMTP delivery cannot be promised exactly
once after a crash during delivery; the CLI does not replay old run notifications.

See [evaluations.md](evaluations.md) for the final evidence against the approved
quality dimensions. No commit, merge, or live production batch was performed.
