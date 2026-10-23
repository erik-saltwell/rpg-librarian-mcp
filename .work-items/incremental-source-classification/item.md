---
name: "Incremental source ownership classification"
status: complete
---

# Incremental source ownership classification

Reduce nightly filesystem work by retaining exact source-version-to-local-file
ownership links, validating the linked copy directly, and building broader local
candidate inventories only when a link is missing or invalid. Retain weekly full
ownership reconciliation and an explicit CLI override.

- [Implementation plan](plan.md)
- Existing safety and quality context: [source sync intent](../brendan-process-batch-refactor/intent.md).

Preserve existing resilience changes and the production recovery run already in
progress. This change takes effect on subsequent invocations.

Completed October 23, 2026. Exact ownership links, direct local-copy verification,
lazy candidate discovery, resumable weekly matching, forced reconciliation and
summary metrics are implemented and documented. Disposable mutation/recovery and
source lifecycle checks, Ruff, formatting, types, CLI help and diff checks passed.
A 1,000-file unchanged fixture reused all links without inventory, content reads or
downloads (0.062 seconds versus 9.881 seconds for the initial classification).
Real SMB performance remains unverified. Existing production recovery continues
with its loaded code; the next invocation establishes links and subsequent quiet
runs use them. No commits, scheduler changes or service restart were performed.
