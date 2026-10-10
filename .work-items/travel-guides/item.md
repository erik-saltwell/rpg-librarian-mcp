---
name: "Travel guide product type"
status: complete
---

# Travel guide product type

Added `travel-guides` to the app's seed product types. Use the publisher or guide
series, such as `Lonely Planet`, as the product line and the individual book as the
product, including its edition when known. Lines remain created on demand using
the existing filing tools.

Updated the app README and bundled process-batch filing guidance. Existing catalogs
receive the new seed by rerunning `init` with their existing library and catalog.
Existing installed skill copies are not overwritten by `init`.

Verified by direct execution against a temporary catalog: fresh initialization,
repair of an existing catalog missing the type, repeated initialization without
duplicates, and visibility through `list_product_types`. Ruff and `git diff --check`
passed.

Applied to production with user approval on 2026-10-10: added `travel-guides`
(type ID 13) to `/home/eriksalt/data/rpg-librarian/catalog.db` using the app models
in one transaction without migrations. Added only the travel-guide judgment bullet
to the production `.claude/skills/process-batch/SKILL.md`. No files were moved;
`Lonely Planet` remains a line to create when filing the first guidebook.

SQLite backup:
`/home/eriksalt/data/rpg-librarian/backups/catalog-before-travel-guides-20261010T171939340372Z.db`.
Original skill backup:
`/home/eriksalt/data/rpg-librarian/backups/process-batch-before-travel-guides-20261010T171939340372Z.md`.

Production verification: `list_product_types` reports the type exactly once with
zero lines/products/files. Compared every row of entry (96,911), product (18,639),
product_line (1,115), and root (2) against the backup using SHA-256 fingerprints;
all were unchanged. Existing product-type rows and schema revision `0006` were
preserved. Skill contents match exactly the original plus the approved bullet.
