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

## Terminal progress follow-up — completed 2026-10-16

The owner observed an active production enrichment stage showing only `enrich...`.
The first implementation captured child output privately and displayed only stage
names. This follow-up adds a separate, stage-owned structured progress snapshot and
a parent display without scraping canonical event logs or private model output.

- TTY display: stage position/name, live elapsed clock, counts/percent when total is
  meaningful, current file/folder/source/tool, errors and waiting since last progress.
  Dynamic pack discovery and filing do not invent a fixed total/ETA.
- Non-TTY/dumb terminal: bounded phase updates and 15-second status while waiting,
  with no ANSI cursor controls. Initial inbox inspection and final reporting are
  visible. Completed stages leave concise metrics and actionable diagnostics links.
- All six stages reviewed: dedupe/scan/enrich/moves name current work before slow
  calls; scan emits extraction substages; enrichment uses query vs entry units;
  packs report folders/cache/model/search activity; filing reports actual catalog
  remaining counts and optional MCP tool activity. Fast SQL counts match the normal
  worklist for present, flagged, resolved and missing-member packs.
- Recoverable per-file issues show the first five affected inputs and then a capped
  further-issues notice. Error warnings retain the first failed operation even when
  cleanup subsequently runs. Untrusted paths are rendered literally, without Rich
  markup or terminal control interpretation.
- Private stdout/stderr, valid agent JSON, stage metrics/outcomes, notification rules,
  process groups, locks, recovery and interruption exit codes remain intact. Only
  optional progress paths/tool status are added to worker/MCP configuration.

Verification (disposable catalogs; no production restart, processing or real email):

- `/tmp/check-batch-terminal.py`: real dedupe, scan, pack/enrichment loops and moves;
  controlled external model/lookup operations; actual agent/MCP writes and encrypted
  loopback SMTP. A 17-second lookup emitted waiting status in redirected output.
  All six progress snapshots and the safe filing-tool snapshot were produced;
  private stderr remained free of hidden Rich progress animations. Real 100-column
  PTY completed with live output. Artifacts `/tmp/rpg-batch-integration-ccc3xnw1/`.
- `/tmp/check-batch-pty.py`: actual 48-column PTY, readable narrow rendering, balanced
  cursor hide/restore and full pipeline completion. Artifacts
  `/tmp/rpg-batch-integration-t7r233u8/`. A direct 80/48-column rendering check caught
  and fixed a bar/detail line-break issue before completion.
- `/tmp/check-batch-terminal-errors.py`: real corrupt image inputs, capped literal
  path warnings, correct execution-issue counts, all no-work stages and filing skip
  explanation, and actual SIGTERM with retained interrupted-stage output/exit 143.
  Artifacts `/tmp/rpg-batch-integration-ql8wy4fq/`.
- Existing `/tmp/check-batch-integration.py` behavior checks passed again, including
  CLI/MCP/image transport, normal/quiet/review runs, fatal/signal/dedupe fallback,
  invalid/failed/partial agent work, safe reruns and SMTP refusal. Log:
  `/tmp/check-batch-progress-regression.log`.
- Ruff lint/format, application ty and `git diff --check` passed. No unit tests,
  suites or tooling were added. No live lookup/model reliability is claimed.

The production launcher already uses this editable checkout, so new invocations
receive the display. The owner's already-running parent was not stopped or changed;
it keeps the old output behavior. No commit or merge was made for this follow-up.

## Production filing failure and mail investigation — 2026-10-17

Completed the fix for run `20261016T215633Z-6f62b4843472`. Claude parsed the skill's
leading YAML `---` as an option because the full prompt was passed in argv. The
prompt now goes through a private mode-0600 file on stdin. Agent stderr now uses
`filing-agent-stderr.log`, preventing the worker traceback from overwriting the
startup diagnostic in `filing-stderr.log`. Existing unattended options, progress,
stdout JSON and owned-process cleanup remain intact.

Read-only Gmail IMAP inspection found the exact Message-ID
`<rpg-batch-20261016T215633Z-6f62b4843472@rpg-librarian.local>`, subject
`RPG Librarian: failed; 750 review item(s)`, dated October 17 at 04:26:59 PDT.
The sender and recipient are the same configured Gmail address. The message is
unread in Sent/All Mail with only the Sent label, absent from Inbox, Spam and Trash
at inspection. An earlier same-address RPG email has both Inbox and Sent labels;
same-address sending alone does not explain this. No matching bounce was found
by Message-ID text search in All Mail. IMAP exposes neither filter rules nor archive
history, so the cause of the missing Inbox label remains unknown. Recommend finding
and moving the message to Inbox, then checking Skip the Inbox filters and other
clients' archive rules. No mail was resent, mailbox rules changed, or production
batch rerun during this investigation.

Future receipts retain sender, recipient, subject, Message-ID and SMTP acceptance
time; abandoned-notification recovery preserves this metadata. Status `sent` means
submission acceptance, not Inbox placement.

Verification:

- `/tmp/probe-filing-cli.py`: installed Claude parser, exact launch flags and full
  prompt stdin accepted; an intentional invalid sentinel stopped before a model
  call. Checked private prompt permissions and absence of the prompt in argv.
- `/tmp/check-filing-stdin.py`: disposable real CLI/MCP/catalog writes and loopback
  SMTP passed success, controlled startup failure, separate original agent stderr
  and worker traceback, SMTP audit fields, safe rerun and 1 MiB file-backed stdin.
  Artifacts `/tmp/rpg-batch-integration-cwsh2fue/`.
- `/tmp/check-batch-recovery.py`: unknown input, shared lock, actual SIGTERM and
  parent SIGKILL recovery/owned-agent cleanup passed again.
- Application Ruff lint/format and ty checks passed; final `git diff --check` passed.
  No unit tests or tooling added. No live Claude model run performed.

Production's editable installation uses this fix on the next invocation. The work
item is complete; provider Inbox placement and filter history remain outside the
verified application behavior.
