---
name: "Refactor rpg-librarian to new app"
status: implementing
---

# Refactor rpg-librarian to new app

Replace `packages/rpg-librarian-mcp` with a ground-up app in `apps/` (src layout)
that runs either as a FastMCP stdio server or as a CLI. Deterministic bulk work
moves into the CLI; the LLM session does judgment only. The catalog database becomes
authoritative and the library filesystem becomes a projection of it, rendered by a
CLI true-up.

## Documents

- [intent.md](intent.md) — intended outcome, scope, constraints, organization
  scheme, working design, folder structure as evidence, settled decisions, rejected
  approaches (including deterministic grouping). No open questions remain.
- [catalog-schema.md](catalog-schema.md) — catalog schema design: entities,
  relationships, creation rules for lines/types/products, invariants, computed target
  path, derived folders, roots and trash, file columns, scan skip rule, per-media
  metadata, aliases, and the `update_product` and read surface. Nothing open.
  Supplements the intent; its changes to the intent are already reconciled into it.
- [plan.md](plan.md) — phased implementation plan: scaffold, catalog and migrations,
  `scan`, `enrich`, MCP surface and `update_product`, `reorganize`, v1 removal. Lists
  the v1 code to port and the agreed decisions. `enrich` includes a simple Google search
  per file, fetched through Serper.dev.
- [progress.md](progress.md) — current handoff: completed phases, actual verification
  outcomes, remaining work.

## Resume note

Status is `implementing`; Phase 0 of `plan.md` is done (see `progress.md`). The catalog location
(`./catalog.db`, with `--catalog` / `RPG_LIBRARIAN_CATALOG` overrides) and the other
plan unknowns are agreed, and Google search will use Serper.dev (`SERPER_API_KEY`;
confirm the key returns results before Phase 3). Continue at Phase 1. Notes:

1. **No rubric exists, by decision.** The user has chosen not to define one for this
   item. Proceed without one and do not report numerical quality scores for it.
2. **Design is fully settled** in `intent.md` and `catalog-schema.md`; neither has open
   questions. Only exact report field names are left to implementation.
3. **Root `pyproject.toml`** is fully wired for `apps/rpg-librarian` (workspace, ruff,
   ty, pytest).
