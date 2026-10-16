---
name: "Move process-batch shell script to a CLI command"
status: complete
---

# Move process-batch shell script to a CLI command

Provide one CLI invocation taking a catalog reference and input folder reference to
run the existing batch pipeline unattended, recover through safe rerunning, save a
local run summary, and selectively email the run outcome and total review backlog
instead of starting interactive review.

See [idea.md](idea.md) for the accepted workshop idea and scope decisions,
[intent.md](intent.md#quality-rubric) for the approved quality rubric, and
[evaluations.md](evaluations.md) for the workshop assessments.

Implemented the CLI, shared review backlog, selective notification, local summaries,
and recovery behavior. The production shell wrapper and installed agent skills are
updated. See [plan.md](plan.md) for completed phases and
[progress.md](progress.md) for verification, production backup location, limitations,
and the disclosed wrapper-check notification incident.

Terminal progress follow-up is complete across all six stages. New invocations
show current activity, counts, elapsed/wait time, bounded error paths and final
review/email status. Actual PTY, redirected-output, error and interruption checks
passed; see progress.md for details. Status is complete. No live production batch or live-model run was started; no
commit or merge was made.
