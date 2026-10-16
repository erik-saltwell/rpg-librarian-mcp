# Qualitative assessment — manual importer, 2026-10-10

Assessed the delivered manual implementation against the approved six dimensions
in [intent.md](intent.md#quality-rubric). Evidence and limitations are detailed in
[progress.md](progress.md). This assessment does not change the rubric or assert
that production rollout is complete.

- **Discovery accuracy:** Full and incremental live discovery agree with the
  preflight eligible inventory. A spread sample of 60 prior ownership assumptions
  passed the new matcher and actual local freshness checks; controlled cases
  reject stale local matches and separate changed remote revisions. Metadata
  ownership still accepts the user's same-name/size tradeoff. Whole-share byte
  accuracy and real production filing accuracy remain unassessed.
- **Organization preservation:** Nested scratch copies preserve source hierarchy,
  and three complete generated token images formed one pack. The transfer barrier
  prevents partial top-level groups from reaching pack discovery. Already-owned
  files are skipped as requested. Published copies retain their old paths after
  a source rename; real Brendan pack quality remains rollout evidence to collect.
- **Operational reliability:** Direct interruption/cursor/publication/revision
  checks, exclusive locks, non-overwriting placement and retained matching
  evidence passed. A completed scratch review reopened scoped placement.
  Long-running real-backlog behavior, post-expiry token refresh and scheduled
  execution remain unverified. Transfers restart rather than resume byte ranges.
- **Resource efficiency:** Actual matching over the live catalog took 2.64 seconds
  with 136.5 MiB peak process RSS in the measured run. Discovery used metadata,
  and the second live cycle reused its delta checkpoint. Bounded transfer attempts,
  reserved byte budgets and exact candidate checks limit RPG downloads. Real
  source throughput and nightly resource usage remain unmeasured.
- **Unattended operation:** Real headless scratch filing completed without input;
  uncertain judgments became review flags, and the next completed group formed
  and filed a pack. Controlled item failures preserve independent work. Large
  folders intentionally wait across manual runs until their transfer group is
  complete. Missing shared filing access is a source-level actionable issue.
- **Review clarity and effort:** Scratch SMTP delivery suppresses empty and
  unchanged digests, retains the full review export, and retries the same pending
  envelope. Existing catalog IDs/reasons and importer source paths give a route
  to corrective action. The real user's effort on actual Brendan reviews and
  production digest readability remain unassessed.
