---
name: "Clean trash and compact catalog"
status: complete
---

# Clean trash and compact catalog

Implement `clean` to permanently remove the library's duplicate, superseded and
discarded trash contents and their catalog records, then compact SQLite. Include
a dry-run preview and retain recoverability after partial failures.

See [plan.md](plan.md).

Implemented and verified. See [progress.md](progress.md) for recovery behavior and
verification. Usage is in [the app README](../../apps/rpg-librarian/README.md#emptying-trash-and-reclaiming-space).
