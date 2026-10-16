---
name: "RPG software product type"
status: complete
---

# RPG software product type

Added `rpg-software` to the app's seed types and documented filing RPG applications
and utilities using the software family or publisher as the product line and the
specific application or release as the product. VTT content packs retain the
existing `vtt packs` type. Updated the app README and bundled process-batch skill.

Applied to production with user authorization on 2026-10-10: added type ID 14 to
`/home/eriksalt/data/rpg-librarian/catalog.db` through the app models in a single
transaction without migrations, and added only the corresponding guidance bullet
to the production `.claude/skills/process-batch/SKILL.md`. No files were moved or
existing products reclassified. Product lines will be created during filing.

Backups:
- `/home/eriksalt/data/rpg-librarian/backups/catalog-before-rpg-software-20261010T172230402483Z.db`
- `/home/eriksalt/data/rpg-librarian/backups/process-batch-before-rpg-software-20261010T172230402483Z.md`

Verified fresh initialization, existing-catalog repair, repeated initialization,
and type listing against a temporary catalog. Ruff and `git diff --check` passed.
Production lists the type exactly once, with zero lines/products/files. Compared
all entry (96,911), product (18,639), product_line (1,115), and root (2) rows against
the SQLite backup using SHA-256 fingerprints; all unchanged. Existing type rows
and schema revision `0006` were preserved. Production skill contents match exactly
the original plus the approved guidance bullet.
