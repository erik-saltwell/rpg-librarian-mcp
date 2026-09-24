---
name: "Per-pack Google lookup for asset media"
status: complete
---

# Per-pack Google lookup for asset media

Make `enrich --source google` look up a *pack* instead of each individual file for
asset media (maps, tokens, art, audio, meshes, and other non-document files). Every
asset file under the same pack folder shares one Serper request and stores that pack
query and its hits as its own evidence row. Product documents (PDFs) keep the existing
per-file query.

Why: `google` was the only source whose `wants()` accepted every file. A token's own
name ("Goblin Archer 03") costs one paid, rate-limited request and finds nothing useful.
The pack folder carries the real signal, and the `process-batch` skill already files
per folder.

## Documents

- [plan.md](plan.md): design, the code inspected, phases, and verification.

## Completion

Implemented 2026-09-24 in `apps/rpg-librarian` (`enrichment/queries.py` `pack_query`,
`enrichment/google.py`, a `begin_run` hook on sources and in `commands/enrich.py`, the
`process-batch` skill, and the README). Verified by lint, type check, the existing suite,
and a simulated run on a copy of the live catalog: 2,540 asset files cost 119 requests
instead of 2,540. See [plan.md](plan.md) for the details and limits.

No quality rubric was defined (the user directed implementation without one), so no
quality dimensions were assessed.

Follow-ups for the user:
- Asset files already in the catalog keep their old per-file Google rows. To redo them,
  delete those rows for non-PDF files, then run `enrich --source google`.
- Libraries that already ran `init` keep their old `process-batch` skill copy. Delete it
  and re-run `init` to pick up the new guidance line.
