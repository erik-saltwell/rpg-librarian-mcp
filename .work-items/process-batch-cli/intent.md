# Process-batch CLI

Provide a single command taking a catalog and input folder to run the existing
batch-processing pipeline unattended, support safe rerunning after interruptions,
and save a local run summary. Selectively email the run outcome and total review
backlog instead of launching interactive review. The accepted workshop idea,
including notification rules and scope, is recorded in [idea.md](idea.md).

## Quality rubric

Approved qualitative dimensions for judging the process-batch CLI and its intended
effect: convenient unattended processing with reliable awareness of outstanding
human review.

- **Ease of routine use** — Values a straightforward invocation with a catalog and
  input folder, understandable scope, and little setup or supervision.
- **Dependable unattended execution** — Values processing that handles interruptions
  and failures without losing completed work or leaving catalog and files
  inconsistent.
- **Trustworthy review awareness** — Values an email that accurately represents the
  complete catalog-wide review backlog, including unresolved items from earlier
  runs.
- **Diagnostic clarity** — Values being able to understand what ran, what completed,
  what failed, and what needs attention afterward.

Dependability and diagnostic clarity are independently assessable: a run might
recover successfully while explaining very little, or explain a failure clearly
while requiring manual recovery. Assess these dimensions in ordinary language,
without scores, rating scales, anchors, weights, or aggregate judgments.
