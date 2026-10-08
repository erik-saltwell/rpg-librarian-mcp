---
name: "Quick duplicate cleanup"
status: complete
---

# Quick duplicate cleanup

Add `quick-dedupe --root PATH` to identify exact duplicates in a large incoming
dump, record only duplicate occurrences, and immediately move them into the
library's existing duplicate trash structure. Unique survivors remain uncataloged
so they can be moved to an unregistered holding folder and processed in batches.

See [plan.md](plan.md) for scope, implementation, and verification.

Implemented and verified. See [progress.md](progress.md) for behavior checks and
remaining performance limitations. Usage is documented in
[the app README](../../apps/rpg-librarian/README.md#quickly-cleaning-a-large-incoming-dump).
