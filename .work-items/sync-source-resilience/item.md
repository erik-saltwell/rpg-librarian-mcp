---
name: "Recover nightly sync and improve source resilience"
status: implementing
---

# Recover nightly sync and improve source resilience

Recover the October 21–23 OneDrive sync failures using existing durable progress,
add bounded transfer retries and token renewal, improve private diagnostics, and
preserve whole-source admission safety when individual files cannot be classified.

- [Implementation plan and verification](plan.md)
- Existing admission intent and quality dimensions: [source sync intent](../brendan-process-batch-refactor/intent.md).

User authorized implementation and a production recovery run on October 23, 2026.

Implementation and controlled verification are finished. Production recovery is
running under the existing service; the full live outcome is still pending. Resume
by reading the live receipt linked in plan.md, checking the service/journal, and
recording the final classification/notification outcome before marking this item
complete. The automatic 100-file limit remains unchanged.
