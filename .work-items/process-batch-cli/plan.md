# Process-batch CLI implementation plan

Status: complete (including terminal progress follow-up). Implementation and behavior-level verification are recorded in
[progress.md](progress.md). This plan implements the
[accepted workshop idea](idea.md), using the approved
[quality rubric](intent.md#quality-rubric). The workshop assessments in
[evaluations.md](evaluations.md) describe design potential, not verified behavior.

## Intended result

```sh
rpg-librarian process-batch --catalog /path/to/catalog.db --root /path/to/inbox
```

Run quick deduplication, scan, pack discovery, enrichment, agent filing, and
reorganization, then save the run outcome and apply the email rules below.
Quick deduplication, scanning, and pack discovery use the selected input root;
enrichment, filing, reorganization, and backlog collection remain catalog-wide.
Never launch interactive `/review-items` at the end.

Every run has a durable local summary. Rerunning the same command preserves
committed work and continues eligible work using existing catalog state.

## Inspected code and implications

All paths in this section are relative to `apps/rpg-librarian/src/rpg_librarian/`
unless otherwise stated.

- `__main__.py` registers verbs, resolves the catalog, loads the application's
  environment, and wraps CLI execution with `CallTracker`.
- `commands/quick_dedupe.py:run` requires an existing registered staging root.
  `commands/scan.py:run` and `commands/find_packs.py:run` also select registered
  roots by exact path. The existing script is `scripts/process-batch.zsh`.
- `commands/scan.py` commits file work incrementally, skips unchanged successful
  files, and retries recorded extraction errors. `ScanStats` does not distinguish
  new, changed, and retry work, so those counters must be added.
- `commands/find_packs.py` caches folder judgments and exposes `Finder.stats`.
  `commands/enrich.py` selects missing evidence and exposes per-source statistics.
  `commands/reorganize.py` computes unsettled placements and commits moves using
  the existing safe placement logic.
- These commands often return zero despite recorded file errors, blocked moves,
  or incomplete source work. Process exit status alone cannot describe a clean run.
- `imports/processing.py:filing` shows how to launch Claude with an explicit
  catalog-bound MCP configuration, no interactive approval, JSON output, and a
  limited tool list. Its Brendan-only manifest and prompt are not a generic batch
  workflow and must not be reused unchanged.
- `imports/notifications.py` implements SMTP SSL/STARTTLS delivery and settings.
  Its Brendan-specific outbox and unchanged-review suppression are not the desired
  batch notification policy.
- `resources/skills/review-items/SKILL.md` defines all four review queues, missing-file
  filters, and organization-finding links. `services/organization_review.py:findings`
  and `model/OrganizationReview.py` provide deferred findings and current identities.
- `observability.py` provides flushed file/stage events and fatal stack capture.
  `imports/state.py:job_lock` protects only Brendan imports today.
- `skills.py` seeds missing installed skills but deliberately does not overwrite
  existing copies. Production uses this editable checkout through
  `~/.local/bin/rpg-librarian`; production skill copies still need explicit updates.

## Planning choices and assumptions

These resolve implementation details for the proposed plan, rather than recording
additional owner-approved workshop decisions:

- **Root interface:** use `--root` for an existing registered staging root, matching
  the current commands and script. Resolve both catalog and root to absolute paths.
  Do not silently widen a descendant folder to its registered parent. Supporting
  arbitrary descendants would require scoped missing-file reconciliation and
  deduplication changes and is outside this first implementation.
- **New scan work:** count newly discovered files and changed size/mtime as new
  input for notification eligibility. Report unchanged-file extraction retries
  separately; retries alone do not constitute new input. Determine eligibility
  before quick deduplication can move new duplicates out of the inbox. Preserve
  that observation through later failures. Reuse the existing walker/exclusions.
- **Email:** suppress when the new-input count is known to be zero, even with an
  existing backlog or a later failure. Otherwise suppress only for successful,
  complete processing with an empty backlog. A nonempty unchanged backlog still
  qualifies when new input exists. If enumeration fails before the count is known,
  report `unknown`, not zero; the planned fallback is a failure email. This fallback
  needs explicit visibility in CLI documentation because it is a planning choice.
- **Counting:** expose counts for each of the four queues. Count an entry once across
  review flags and blocked moves, preserving both reasons. Count folder judgments
  by `(root_id, folder)` and organization findings by finding ID. Collapse marker-only
  flags linked to a deferred organization finding into that finding, preserving
  unrelated flag text as its own entry review. Do not merge unrelated overlapping
  folder/group concerns merely because they involve the same files. Label the total
  as outstanding review items, not physical files or conflict-resolution actions.
- **Failures:** quick-deduplication failure is a recorded warning and scanning still
  runs. A fatal exception, signal, or invalid/missing result from a subsequent stage
  stops dependent processing stages; reporting still runs. Recoverable file/source
  errors retain committed results and are reported as issues. Do not call a run
  clean merely because its subprocesses returned zero.
- **Recovery:** recompute eligibility and unfinished work from the catalog on every
  invocation; do not blindly replay a previous run's IDs or skip a whole stage based
  only on an old completion marker. New-input/email rules apply to the current
  invocation, including recovery invocations.

## Phase 1 — Shared review backlog

- [x] Add `services/review_backlog.py` to collect the complete backlog in one database
  snapshot, with stable item keys, queue membership, category counts, and a total.
  Match the skill's SQL filters and deferred-organization semantics; do not impose
  MCP pagination limits on internal collection or truncate before counting.
- [x] Implement the overlap rules above, including packs as one entry and findings
  whose historical entry IDs changed after pack edits.
- [x] Expose the collector as a read-only MCP tool, `review_backlog`, and update the
  bundled review-items instructions to obtain counts/identities from this shared
  source while preserving the skill's investigation and confirmation rules.
- [x] Verify with disposable catalogs containing each queue, overlapping entry
  reasons, linked organization flags with unrelated text, missing files, resolved
  items, and enough rows to exceed current MCP query limits. Compare the resulting
  backlog with the existing review-items queries before changing their use.

Outcome: CLI notification and interactive review use the same backlog definition.
This supports trustworthy review awareness.

## Phase 2 — Durable run records and isolated stages

- [x] Add a small `batch/` package for orchestration, stage execution, and run records;
  keep `commands/process_batch.py` as the CLI adapter. Register `process-batch` and
  its required `--root` plus existing `--catalog` handling in `__main__.py`.
- [x] Write private run records under
  `logs/process-batch/<run-id>/summary.json` beside the catalog, using atomic writes.
  Save resolved inputs, timestamps, PID, current stage, per-stage outcomes/counts,
  new/changed/retry observations, backlog counts, and notification status/reason.
  Print the summary path at the start and end. Retain records; automatic pruning
  is outside this change.
- [x] Persist the initial record before starting processing, and stage-start records
  before launching children. A parent killed abruptly leaves an inspectable
  incomplete record. A later invocation marks abandoned runs interrupted after
  acquiring the orchestration lock; no external watchdog is introduced.
- [x] Execute processing stages in child processes using `sys.executable`, explicit
  catalog paths, and argument lists. A small internal worker calls the existing
  handlers and returns structured JSON metrics; do not scrape console output or
  global event-log tails. Preserve child return code/signal and per-stage stderr.
  Preserve fault-handler capture and correlate all records with a batch run ID.
- [x] Add narrowly scoped new/changed/retry scan counters and needed structured
  stage fields. Existing standalone command return conventions remain compatible.
- [x] Protect process-batch runs and Brendan imports for the same catalog with one
  shared orchestration lock. Preserve Brendan's existing source lock; avoid nested
  reacquisition by child stages. This does not claim to lock unrelated interactive
  MCP writers or every standalone command.
- [x] Verify child success, handled errors despite exit zero, nonzero exit, missing
  result, deliberate disposable-child SIGSEGV, parent interruption, and lock release.
  Confirm durable summaries survive without touching production content.

Outcome: the parent can report processing-stage crashes and quiet runs remain
inspectable. This supports diagnostic clarity and unattended execution.

## Phase 3 — Existing pipeline and safe rerunning

- [x] Before mutations, validate the catalog, registered staging root, reachable
  library, writable summary directory, and Claude executable. Capture the input
  inventory needed for new-work eligibility. Preserve inherited loaded environment
  without exposing credentials in summaries or subprocess arguments.
- [x] Wire quick deduplication, scan, find-packs, enrich, and reorganize to existing
  handlers through the stage worker. Supply each handler's expected defaults
  explicitly. Do not pass the input-root scope into catalog-wide stages.
- [x] Implement stage outcome mapping from structured counters, not exit code alone:
  distinguish fatal failure, handled issues, deliberate skips, and successful
  completion. Include enrichment early stops, unreachable roots, discovery errors,
  scan errors, and blocked/failed placements. An incomplete filing worklist also
  prevents claiming everything was processed.
- [x] Continue after quick-deduplication failures as agreed, recording the warning.
  Stop dependent stages after a fatal later failure. Finalize the local report and
  attempt an honest backlog snapshot even after failure; represent an unavailable
  count as unknown rather than zero.
- [x] Reuse catalog-based skip/retry and placement behavior. Do not reset decisions,
  force enrichment, refile already resolved entries, or perform blanket rollback.
  A no-new-input run still executes outstanding catalog-wide work; email suppression
  is not an instruction to skip the pipeline.
- [x] Verify scope with a disposable catalog containing another staging root and
  old catalog-wide work. Interrupt after committed scanning, filing, and placement,
  then rerun. Check that existing decisions and file hashes survive and completed
  moves are not repeated. Verify unchanged extraction failures can retry without
  being counted as newly arrived input.

Outcome: the ordinary invocation performs the script's work and recovers from
partial progress without manual cleanup.

## Phase 4 — Catalog-bound unattended filing

- [x] Implement a generic batch filing launcher using the established Claude CLI
  pattern in `imports/processing.py`; leave Brendan-specific scope and behavior
  intact. Build the prompt from the bundled process-batch instructions with explicit
  unattended overrides: never wait for approval; use visual tools when useful; defer
  unresolved judgments with a review reason and continue.
- [x] Give the agent an explicit MCP configuration bound to the requested catalog,
  independent of the caller's working directory or installed slash-command copy.
  Clear inherited Brendan manifest restrictions for this generic catalog-wide run.
  Limit tools to the filing/read/pack operations the skill requires, including
  `view_file`; do not grant arbitrary shell tools or `rename-file`.
- [x] Preserve the intended catalog-wide filing scope and refresh the unflagged
  worklist to check completion. Check Claude's exit status, JSON `is_error`, tool
  availability failures, and remaining eligible entries; distinguish unfinished
  work from successfully deferred review items. Save private raw agent output only
  in the run directory, not in email or general logs.
- [x] Ensure a failed or terminated launcher stops its owned Claude/MCP process
  group before releasing the orchestration lock; use bounded termination cleanup.
  Never terminate unrelated agent sessions. Preserve decisions already committed.
- [x] Verify with a temporary executable simulating Claude and an actual local MCP
  transport: explicit catalog routing from another working directory, image tool
  availability, pack operations, invalid output, reported error, unfinished work,
  and partial committed decisions. Live model verification is a separate controlled
  disposable-catalog check, not a production batch or assumed result.

Outcome: the CLI needs neither interactive review nor implicit project MCP setup.
This supports routine usability and safe rerunning.

## Phase 5 — Notification and summary finalization

- [x] Extract reusable SMTP message delivery/settings into a small shared helper,
  keeping the Brendan notification policy, state, recipient settings, TLS behavior,
  and unchanged-review suppression intact. Reuse the current SMTP/recipient env vars.
- [x] Add batch-specific policy using the durable new-input observation, actual
  processing outcome, and current backlog. Apply the exact suppression order above.
  Send the run result, completed/failed/skipped stages, total and category backlog
  counts, catalog/root identifiers, and local summary path; avoid document text.
- [x] Save `pending`, `sent`, `skipped` with reason, or `failed` with a safe diagnostic
  in the run summary. A delivery failure must remain visible and produce a nonzero
  command result; it must not undo processing or claim notification succeeded.
  Do not automatically resend old run emails on a no-new-input rerun. SMTP acceptance
  followed by a parent crash can leave delivery uncertain; do not promise exactly-once
  delivery or blindly retry ambiguous sends.
- [x] Define exit behavior: zero only when processing completed without reported
  execution issues and any required notification succeeded; nonzero for failure,
  incomplete processing, or delivery failure. Review backlog by itself is not an
  execution failure. Preserve conventional interruption exit codes.
- [x] Verify using a local SMTP capture server: no new input with backlog; no new
  input with later failure; clean new input with zero backlog; new input with old
  unchanged backlog; new input with failure and zero backlog; unknown inventory;
  unavailable backlog; and SMTP refusal. Assert both message behavior and summary
  reasons, without sending real email.

Outcome: notifications reflect both outcomes and the total review burden while
respecting the owner's quiet-run rules.

## Phase 6 — Documentation, production handoff, and verification

- [x] Document invocation, exact root requirements, email settings/policy, definition
  of new input, overlap counting, summary paths, safe rerunning, exit behavior, and
  hard-crash limitations in `apps/rpg-librarian/README.md` and root usage docs.
- [x] Replace repository `scripts/process-batch.zsh` with a thin forwarding wrapper,
  preserving its default inbox and argument/exit behavior. Keep interactive
  `/review-items` available as a separate owner action.
- [x] During implementation, back up and update
  `~/data/rpg-librarian/process-batch.zsh` and affected production skill copies for
  Claude, Codex, and Gemini. Inspect local differences before syncing, preserve
  custom instructions, and leave the Brendan-specific launcher working. MCP server
  instructions should expose shared backlog usage; do not populate user-maintained
  `.agent_context.md` with inferred facts. Verify production's executable still
  resolves to the intended source checkout; restart/discover tools in new sessions.
- [x] Run Ruff lint/format, targeted ty checks, and `git diff --check`. Execute the
  new CLI against disposable catalogs through the real command line and actual MCP
  transport, using local SMTP and a controlled agent stand-in. Cover two successive
  normal runs and an interrupted/retried run. Add no unit tests, test suites,
  unit-test tooling, or test-driven steps; preserve existing tests.
- [x] Record actual behavior-level results, limitations, and qualitative evidence
  against each approved rubric dimension. Update plan checkboxes/progress and mark
  complete only after implementation and appropriate verification are finished.

## Dependencies and limits

Phases 1 and 2 establish the backlog definition and reporting mechanism. Phase 3
uses phase 2; phase 4 completes its filing stage. Phase 5 depends on the shared
backlog, run records, and outcome mapping. Phase 6 follows integrated verification.

The labeled planning choices above were used for implementation. Descendant-folder
support or different new-input/counting semantics would be subsequent changes.
Actual verification, production instruction updates, limitations, and the wrapper
check notification incident are documented in progress.md. Hard termination of the parent or machine can prevent
final reporting; durable stage-start records support later diagnosis and recovery,
not immediate notification in that case.

## Terminal progress follow-up

The owner observed that only stage names were visible during a production run.

- [x] Add a stage-owned structured progress channel and parent terminal rendering,
  with TTY live display, bounded plain-text updates, elapsed time and wait status.
- [x] Review all six stages: counts/current file for dedupe/scan/enrichment/moves,
  current folder and request counts for pack discovery, real catalog decision
  progress and activity for filing, plus startup/reporting and stage summaries.
- [x] Preserve private child/agent logs, JSON results, scope, error outcomes,
  notification policy and owned-process cleanup. Avoid document/model output dumps.
- [x] Verify real CLI output under PTY and redirection using disposable catalogs,
  controlled network/agent/SMTP, slow work, errors, no work and interruptions.
  Run lint/types/format checks. No unit tests or live production run/restart.
- [x] Document progress behavior and record completion/rubric evidence.

## Production filing failure and email investigation

- [x] Send the complete leading-dash skill prompt via private stdin input instead
  of argv, preserving unattended options, progress and process cleanup.
- [x] Give Claude a distinct stderr path so worker exceptions cannot overwrite its
  startup failure, and point diagnostics at the correct file.
- [x] Check the installed Claude parser without a model call, then verify real
  CLI/MCP boundaries with a controlled agent and captured SMTP, including failure
  and interruption. Preserve stdout JSON and decisions; no new unit-test suite.
- [x] Trace historical failure notification eligibility, SMTP result, configuration
  and relevant mailbox evidence using read-only access. Do not resend live mail or
  expose secrets. Distinguish submission acceptance from inbox delivery.
- [x] Record evidence, limits, documentation and final status.
