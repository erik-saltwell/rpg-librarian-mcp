# Implementation plan

Implement the approved `review-organization` skill and accepted workshop behavior. Existing code inspected: SQLModel catalog entities, Alembic 0006, per-call transactional MCP wrappers, product assignment services, pack membership services, the bundled skill installer, and review-items.

- [x] Add additive database migration and models for resumable runs, group coverage, findings, and owner decisions. Preserve historical findings when pack operations replace entry identities.
- [x] Add MCP tools to start/resume a bounded pass, inspect paginated groups and decision history, commit a complete group correction or recommendation, return a receipt, and resolve recommendations. Validate snapshots and touched groups in one transaction; failed corrections become review items without partial catalog changes.
- [x] Package `review-organization`, specifying reliable evidence, respect for editions and owner decisions, whole-group review, and automatic corrections through the transaction tool. Update review-items to display and resolve organization recommendations. Install usable skill copies without overwriting unrelated customizations.
- [x] Verify migrations, MCP transport, resumability, stale snapshots, rollback, pack identity changes, review preservation, and decision memory on isolated catalogs. Run lint, formatting, types, existing checks, and skill validation; no new unit tests or test tooling.
- [x] Record outcome, rubric assessment, and practical limitations.

Implementation choices: groups are products (with paginated entry/member context and neighboring lines) and unassigned source folders; cross-group corrections require current snapshots of both sides. Runs are bounded and resumable. Database review records survive entry deletion. Catalog corrections do not move or delete files; physical placement uses the existing separate reorganize command.
