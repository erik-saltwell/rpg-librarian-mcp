# Workshop evaluations

These are qualitative judgments of an unbuilt idea's apparent potential, not
observations of implemented behavior. Both assessments use the approved dimensions
in [intent.md](intent.md#quality-rubric); those definitions were unchanged throughout
the workshop.

## Initial saved idea

Version: the idea kernel before the workshop, with one batch invocation and an
email whenever the complete review backlog was nonempty.

- **Ease of routine use:** One invocation removes manual command coordination and
  attendance at a final review session.
- **Dependable unattended execution:** Recovery behavior was not established;
  dependability remained unassessed.
- **Trustworthy review awareness:** All four review queues, including older items,
  make the count useful beyond the latest batch. The count alone does not establish
  that processing finished.
- **Diagnostic clarity:** Backlog notification does not distinguish completion
  from a run that stopped partway through.

## Accepted workshop revision

Version: [the accepted workshop idea](idea.md), including selective email with run
outcome, a local summary for every run, and recovery by safely rerunning the same
command. The owner approved these changes and closed the workshop.

- **Ease of routine use:** One invocation serves ordinary processing and recovery.
  Suppressing email for no-new-scan runs and clean runs without reviews reduces
  unnecessary attention; the local summary supports checking quiet runs later.
- **Dependable unattended execution:** Preserving completed work and continuing
  outstanding work gives the design a clearer recovery promise. Actual reliability
  remains unassessed pending implementation and behavior-level verification.
- **Trustworthy review awareness:** Qualifying emails retain the complete
  catalog-wide backlog, including unchanged unresolved items. Quiet runs retain
  that information locally; a no-new-scan run deliberately sends no email even
  when a backlog exists.
- **Diagnostic clarity:** Outcome and stage information distinguish completion
  from partial failure. The local summary also explains intentional email
  suppression. Hard crashes that prevent reporting remain a limitation requiring
  detailed design and implementation evidence.

The workshop ended because the accepted changes addressed the main operational
concerns without expanding the idea into a general workflow system. Remaining
questions concern detailed design, including review-count overlap and recognizing
completed work during retries. No further stage was started.

## Implemented command

Version: implementation and behavior checks recorded in [progress.md](progress.md).
The approved rubric definitions in intent.md remain unchanged.

- **Ease of routine use:** The production wrapper forwards to one CLI invocation,
  anchored to its catalog regardless of caller directory. The CLI supplies its own
  filing instructions and MCP configuration. Real command-line checks showed both
  normal invocation and rerunning completed/partial work without manual cleanup.
- **Dependable unattended execution:** Disposable integration checks demonstrated
  preservation of committed decisions and moves across stage errors, SIGSEGV,
  graceful termination and parent SIGKILL. Catalog-state reuse and a cooperative
  job lock supported recovery. Live-model behavior and external-service reliability
  remain unassessed; abrupt machine failure still prevents immediate reporting.
- **Trustworthy review awareness:** Snapshot collection, overlap/marker filtering,
  changed pack identities and pagination were verified with 519 items. Loopback SMTP
  capture verified quiet-run rules, unchanged-backlog notifications with new input,
  unknown counts and delivery failure. Brendan's unchanged-digest suppression was
  retained. The production schema was checked read-only. One real failure email was
  accidentally sent during a mis-isolated wrapper check; the incident and corrected
  verification are recorded in progress.md.
- **Diagnostic clarity:** Atomic receipts and per-stage logs preserved the active
  stage, processing result, signal, counters and notification reason through the
  exercised failures. A stage exit of zero did not conceal handled errors. Recovery
  marked abandoned runs interrupted, while unavailable counts stayed unknown.
  Delivery uncertainty during an abrupt SMTP interruption remains explicit.

## Terminal progress follow-up assessment

Evaluated the completed 2026-10-16 follow-up against the unchanged rubric in intent.md.
The owner's observed production run exposed a diagnostic usability gap in the prior
version: private evidence existed, but a long stage appeared idle in the terminal.

- **Ease of routine use:** the invocation is unchanged; an actual terminal shows
  current activity/counts and elapsed time. Redirected output remains readable.
  Real 48/100-column PTY and a slow redirected lookup were checked.
- **Dependable unattended execution:** existing crash/agent/mail behavior checks
  still pass, and actual SIGTERM restores output and returns 143. Display writes
  are optional and child logs/results stay separate. Live cloud behavior unassessed.
- **Trustworthy review awareness:** final terminal reporting includes the shared
  backlog and notification status/reason; existing quiet/review/SMTP checks passed.
  The collector and email eligibility policy were not changed by this follow-up.
- **Diagnostic clarity:** all six stages expose meaningful progress and summaries;
  waits identify elapsed time since reported activity, not an asserted stall.
  Corrupt inputs show bounded affected paths and the first failed operation.
  Pack/filing activity avoids invented fixed totals. Large-library display overhead
  and long live-agent sessions remain unmeasured; controlled integration verified
  the actual CLI/MCP/status boundary and 17-second lookup waiting behavior.

## Filing and mail follow-up assessment — 2026-10-17

Evaluated the completed fix against the unchanged approved rubric in intent.md.

- **Ease of routine use:** invocation unchanged; installed parser accepts the full
  skill through stdin. Live model execution remains unassessed.
- **Dependable unattended execution:** controlled CLI/MCP success, failure and safe
  rerun passed, along with actual SIGTERM/SIGKILL cleanup and recovery checks.
- **Trustworthy review awareness:** captured SMTP verified failure notification and
  audit metadata. Gmail contains the historical production message; Inbox placement
  and the responsible rule/client remain unassessed.
- **Diagnostic clarity:** agent stderr survives beside the worker traceback, and
  receipts retain message identifiers and submission time for future mail tracing.
