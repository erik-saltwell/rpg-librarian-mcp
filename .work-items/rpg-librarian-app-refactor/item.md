---
name: "Refactor rpg-librarian to new app"
status: fleshing-out
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

## Resume note

Intent is saved and covers the settled architecture. It has been reconciled with
`catalog-schema.md` (`vtt packs`, LLM-creatable types and lines, `update_product`
creation rules, `missing_since` for moved files) and links to it. The root
`pyproject.toml` is partly wired for `apps/rpg-librarian` (workspace and ruff; the
ty and pytest entries wait for the app skeleton, see the intent's Constraints). Next
is planning; notes:

1. **No rubric exists, by decision.** The user has chosen not to define one for this
   item. The workflow's rubric gap is therefore acknowledged and accepted, not
   pending: proceed to planning without one, and do not report numerical quality
   scores for this item. Revisit only if the user asks.
2. **`intent.md` has no open questions left.** Deterministic grouping was declined,
   throughput accepted as a limitation (folder structure is exposed to the LLM as
   evidence), `reorganize` is CLI-only, and the `vtt` question is resolved. The
   disposition model has been ratified. The schema's open list is also complete:
   roots and `.trash/` location, core `file` columns, scan skip rule, per-media
   tables, aliases, the `update_product` signature, and the reads (including
   `pending_changes`) are all recorded in `catalog-schema.md`. Only exact report
   field names are left, for implementation time.
