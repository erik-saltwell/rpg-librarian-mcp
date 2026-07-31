# Ingestion — spec

Design reached via brainstorm on 2026-07-30, implemented the same day.
Covers how new content enters the library for the two real-world scenarios
that motivate it, and the two new tools/fields they require.
**Status: complete.** See `tools_spec.md` (Tool 12, the `content_role`
prerequisite, Tool 13) for implementation-notes-level detail and file
pointers; this document stays the scenario-level design record.

## Scenarios

1. **Friend handoff.** A friend gives you a pile of content to fold into the
   shared library. Much of it duplicates what you already have; the goal is
   to find the genuinely new material and integrate only that.
2. **New purchase.** You buy a new RPG system: a core rulebook, character
   sheets, and a sample adventure. The goal is to get it identified, grouped
   into product(s), classified by content role, and filed in the target
   organization scheme (`CLAUDE.md`'s system → role → product hierarchy).

## Constraint that shapes the design

`Entry.parent_path` (`model/core.py`'s `ParentPathType`) is validated as
relative to the library root — it cannot represent a path outside it. A
friend's drive is therefore never catalogable in place; it must be copied
into the library root before any `Entry` row can exist for it. This rules
out "dedup before copying" as a catalog-level operation and settles the
overall shape of scenario 1: **copy into a staging area first, then run the
normal cataloging pipeline on the staged copy.**

Staging area: `_inbox/<name>/` inside the library root (`<name>` is a
caller-supplied label for the source, e.g. the friend's name).

## New tool 1 — `ingest_external_source(source_path, name)`

Copies only the *new* content from an external path into `_inbox/<name>/`,
skipping anything byte-identical to something already in the library or
already staged from a prior run. This is the one new capability scenario 1
needs; everything after it reuses the existing pipeline
(`update_catalog` → `read_pdfs` → `update_product` →
`classify_content_role` → `move`) unchanged.

```python
def ingest_external_source(source_path: Path, name: str) -> dict[str, object]:
    """Copy new (non-duplicate) content from an external path into
    `_inbox/<name>/`, deduping by content hash against both the library
    and any previously staged content under the same name."""
```

- `source_path` is an **absolute path outside the library root** — the one
  deliberate exception to the "every tool path is library-relative" rule
  used everywhere else, since by definition this content isn't in the
  library yet.
- **Dedup key: exact `sha256` match**, nothing fuzzier. A file is skipped
  iff its hash matches an existing `Entry.sha256` row *or* the hash of a
  file already present under `_inbox/<name>/` (from an earlier run against
  the same source). Near-duplicates (re-scans, different editions, a v1.2
  vs v1.0 PDF of the same book) are **not** caught here — deliberately
  out of scope for this tool; they surface downstream at `update_product`
  time as two products that may turn out to be "the same thing," which is
  a judgment call, not a hash comparison.
- **Idempotent across re-runs.** Hashing the existing `_inbox/<name>/` tree
  (not just querying `Entry`) means running this tool twice against an
  updated/re-shared drive never double-copies content still sitting
  unintegrated from the first run.
- **Structure-preserving copy.** Source subfolders are mirrored under
  `_inbox/<name>/` — flattening would destroy the folder-groups-a-product
  signal that `update_product` and the target org scheme both rely on.
- **Report file, not an inline manifest.** A drop can be thousands of
  files; returning a full per-file manifest inline risks flooding the tool
  response/context window. Instead:
  - Every copied file, and every skipped file *with the library/staged
    path it matched*, is written to `_inbox/<name>/_ingest_report.md`.
  - The tool call itself returns just summary counts plus the report path.

Response shape:
```json
{
  "source_path": "/media/friend-drive/rpg-stuff",
  "name": "dave",
  "scanned": 4213,
  "copied": 340,
  "skipped_duplicate": 3873,
  "report_path": "_inbox/dave/_ingest_report.md"
}
```

Report file shape (`_inbox/dave/_ingest_report.md`):
```markdown
# Ingest report — dave (2026-07-30)

## Copied (340)
- Chaosium/Petersen's Abominations/Abominations.pdf -> _inbox/dave/Chaosium/Petersen's Abominations/Abominations.pdf

## Skipped as duplicate (3873)
- Chaosium/Call of Cthulhu/Keeper Rulebook.pdf -> matches books/Systems/Call of Cthulhu/Keeper Rulebook 7e.pdf
```

## Prerequisite for scenario 2 — `Product.content_role`

Neither `Entry` nor `Product` currently carries the content-role axis
`CLAUDE.md`'s target scheme files system-specific content by (Core Rules /
Adventures & Scenarios / Settings & Supplements / GM & Player Aids /
Extras). Without it, nothing in the catalog can drive where a product
belongs under a system folder — this is the actual blocker for scenario
2's placement step; identification and grouping are already fully covered
by `update_product` + the lookup tools.

New field on `Product` (`model/Product.py`):

```python
class ContentRole(StrEnum):
    core_rules = "core_rules"
    adventures_and_scenarios = "adventures_and_scenarios"
    settings_and_supplements = "settings_and_supplements"
    gm_and_player_aids = "gm_and_player_aids"
    extras = "extras"


class Product(EntityBase, table=True):
    ...
    content_role: ContentRole | None = Field(default=None, nullable=True, index=True)
```

Nullable: agnostic products (`Product.system == Product.AGNOSTIC`) never
get a role — the target scheme files them by media type/publisher instead,
so `content_role` staying `None` for them is the correct, meaningful state,
not a gap to fill.

Requires a migration (new nullable column, matches the `product_id`
FK-on-`Entry` precedent).

## New tool 2 — `classify_content_role(path, process_recursively=False, force=False)`

An `UpdateBaseCommand`-shaped tool, same family as `read_pdfs` and
`update_product`: takes a path, resolves the `Entry` rows under it, and for
each one determines and writes its product's `content_role` via an LLM
judgment call.

```python
async def classify_content_role(
    path: Path,
    ctx: Context,
    process_recursively: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Classify each entry's product into a content role (Core Rules /
    Adventures / Settings & Supplements / GM & Player Aids / Extras) using
    an LLM judgment over the product's description and any linked PDFs'
    sample text. Skips agnostic products and products with no usable text."""
```

- **Input text, reused not re-extracted:** `Product.description` plus
  `PdfContents.sample_text`/`description` for any PDF entries already
  linked to the product. No independent OCR/extraction — `read_pdfs` is
  the only place that happens, and this tool assumes it has already run
  where applicable (same pipeline ordering as `update_product`'s existing
  dependency on it).
- **`in_scope`:** false whenever the entry's product has
  `system == Product.AGNOSTIC` — role is meaningless there, and skipping
  early avoids a wasted LLM call.
- **`should_process`:** true only when the product has no `content_role`
  yet, or has a recorded error for this stage — i.e. classify once per
  product and treat a set `content_role` as done, not "always try again."
  Since a product can span several entries (a rulebook + its own map
  images), this means only the first entry with usable text triggers the
  LLM call; every other entry under the same product is then a cheap skip.
  `force=True` bypasses this and reclassifies unconditionally.
- **No text available:** neither `Product.description` nor any linked
  `PdfContents.sample_text` exists for the product — `should_process`
  returns false, the entry is skipped (not errored). Re-run after
  `lookup_isbn`/`lookup_rpg_geek_product`/`read_pdfs` has populated one of
  those fields.
- Writes `Product.content_role` directly (`session.merge`/`session.add` on
  the resolved `Product`, same as `UpdateProductCommand` does for its own
  fields) — no separate raw per-source table, since this is a single
  curated judgment, not raw per-source signal awaiting reconciliation
  (contrast `PdfContents.possible_system`, which does feed a later
  curation step onto `Product.system`).

Response shape: standard `UpdateResult._asdict()` plus `errors`, same as
`read_pdfs`/`update_metadata`.

## Placement — no new tool

Once `Product.system` and `Product.content_role` are both populated, the
target destination path is a one-line formula
(`<system>/<content_role folder>/<product title>/` or, for agnostic
content, `system agnostic/<media type>/<publisher-or-misc>/<product
title>/`). Computing it and calling the existing `move` tool is left
manual rather than adding a `place_product` tool — the formula is trivial
once the fields exist, and automating it is deferred until manual placement
turns out to be actual friction in practice, not assumed up front.

## End-to-end flows

**Scenario 1 — friend handoff:**
1. `ingest_external_source(source_path, name)` — copies new content into
   `_inbox/<name>/`, skipping exact duplicates already in the library or
   already staged.
2. Normal pipeline on `_inbox/<name>/`: `update_catalog` →
   `read_pdfs` → identify (`lookup_isbn`/`lookup_rpg_geek_product`/
   `search_dtrpg`/manual) → `update_product` → `classify_content_role`.
3. Manual `move` into the target organization scheme.

**Scenario 2 — new purchase:**
1. `update_catalog` on wherever the purchase landed.
2. `read_pdfs` for PDF sample text/description.
3. Identify via `lookup_isbn`/`lookup_rpg_geek_product`/`search_dtrpg`, or
   `manual`. Core rulebook, character sheets, and sample adventure are
   likely **separate `Product`s** (each sold/distributed as its own unit
   per `CLAUDE.md`'s product definition) unless bundled as one purchase.
4. `update_product` per product.
5. `classify_content_role` per product.
6. Manual `move` into the target organization scheme.
