---
name: "Sync registered sources through the process-batch pipeline"
status: complete
---

# Sync registered sources through the process-batch pipeline

Implemented a named source registry, OneDrive provider supporting multiple folders
and accounts, and `sync-sources` for independent threshold decisions followed by
serial download and shared batch processing. Exact hash matching excludes owned
content; durable admissions resume after interruptions; source failures continue
and produce one combined email.

- [Approved intent and rubric](intent.md)
- [Design, completed plan and verification](plan.md)
- [Completion handoff](progress.md)
- [Qualitative assessment](evaluations.md)
- [Original idea history](idea.md)

Controlled CLI/Graph/MCP/copy/SMTP behavior checks, crash recovery, standalone batch
regression, Ruff, formatting, ty and diff checks passed. Production launchers and
private registry are ready, with backups. No live cloud/Claude import, real email,
scheduler installation or commit was performed. The first real run resumes existing
unfinished Brendan publication before fresh classification; initial reconciliation
of old metadata matches can be expensive.
