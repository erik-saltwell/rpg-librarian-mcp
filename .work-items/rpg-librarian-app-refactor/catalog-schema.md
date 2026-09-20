# Catalog schema design

Supplements [intent.md](intent.md). That document deferred the concrete shape of the
catalog ("Product-line gets normalized identity ... concrete shape deferred to schema
design"); this one records the shape worked out with the user in a design session.
Every decision below was explicitly chosen or agreed by the user unless listed under
"Open". Table and column names are working names, not final identifiers.

The existing v1 models (`packages/rpg-librarian-mcp/src/rpg_librarian_mcp/model/`)
were the starting point. v1's shape survives in outline (a file table with a nullable
product foreign key, one metadata table per media type), but the schema is new and
does not migrate v1's alembic chain.

## Changes to intent.md

These modified or extended what `intent.md` said. They have since been reconciled
into it, and are kept here as a record of where the schema design changed it.

- **Product type `vtt` is renamed `vtt packs`.** The content is collections of tokens
  and other material used in a virtual tabletop, not virtual tabletops themselves.
  This resolves the intent's open question about `vtt` as a type.
- **`update_product` is specified.** Creation rules with `create_line` and
  `create_type` flags (see "Creating lines, types, and products"), and the full
  signature (see "The MCP surface over the schema"). The intent left both open.
- **The LLM may create product types**, through `update_product`. The intent did not
  say who could. This was the user's choice over a recommendation to keep types
  closed to the LLM.
- **Moving a file by hand** is handled by the `missing_since` mechanism below. The
  intent's statement that a re-scan "re-identifies it by hash" holds, but a naive hash
  match would have mislabelled the moved file as a duplicate.

## Entities

| Table | One row per | Written by |
|---|---|---|
| `root` | registered location: the library, or a staging dump | `init`, `add-source` |
| `product_type` | function-based type (`games`, `maps`, `vtt packs`, ...) | `init`; `update_product` with `create_type` |
| `product_line` | game, model line, or publisher within one type | `update_product` with `create_line` |
| `product_line_alias` | alternate name for a line | `update_product` with `create_line` / `aliases` |
| `product` | set of files that shipped together | `update_product` |
| `file` | physical file occurrence on the share | `scan`, `update_product` |
| per-media metadata tables (`pdf_`, `image_`, `audio_`, `video_`, `mesh_metadata`) and `file_metadata` | file of that media type; `file_metadata` for any file | `scan` |
| `file_text` | file (PDFs) | `scan` |
| `file_text_analysis` | file | `enrich` |
| `dtrpg_result`, `rpggeek_result`, `isbn_result`, `google_search_result` | file, per source | `enrich` |
| `error` | file and stage | `scan`, `enrich` |
| `review_flag` | LLM deferral on a file | `update_product` / session |

Relationships: `file.root_id` → `root`; `file.product_id` → `product` (nullable);
`product.product_line_id` → `product_line`; `product_line.product_type_id` →
`product_type`; `file.duplicate_of_id` → `file` (nullable, self-reference).

## Decisions and reasoning

### A file row is a physical occurrence

A file is identified by `(root_id, relative_path)`. `sha256` is indexed but **not**
unique. Each physical copy needs its own disposition and path so `reorganize` can move
a duplicate to `.trash/duplicates/`; a content-keyed table would need a second table
for that per-copy state anyway. "Do I already have this?" stays a hash join.

Paths are stored relative to a `root`. v1 keyed files on `(parent_path, filename)` with
no root, which would collide across dumps (`dump_A/maps/x.pdf` vs `dump_B/maps/x.pdf`).
The root's `kind` (library or staging) answers "is this still in a dump?" without path
matching, and a changed share mount point is a one-row update.

### Product lines and types

- A product line belongs to exactly one type (`product_line.product_type_id`). A brand
  that spans types needs one line row per type: "Dungeons & Dragons" under `games`,
  generic D&D map packs under `maps`.
- A line is unique on `(product_type_id, name)`, with an alias table so "D&D 5e" and
  "Dungeons & Dragons" resolve to one line.
- The seed list of types is a constant in code; `init` inserts any that are missing
  (idempotent, and repairs a catalog missing a row). Adding a type is a code change,
  not a migration.

### Creating lines, types, and products

`update_product` is the one writer and has these creation rules:

| Name given | Behaviour |
|---|---|
| Unknown product line | Rejected, with the closest existing lines, unless `create_line: true` |
| Unknown product type | Rejected, with the closest existing types, unless `create_type: true`, which implies `create_line` |
| Unknown product name within a line | Created on first use, with a warning when the name is close to an existing product in that line |

Reasons: the line is the coordinate that must match across separate sessions, and
rejection at write time stops "D&D 5e" from silently becoming a second line before
`reorganize` has put files in two folders. A type is a top-level folder on the share, so
a typo would create a stray sibling folder; it therefore needs its own deliberate flag.
Products are far more numerous and a wrong one is cheap to correct in the database, so
they warn rather than block. The LLM does not need the full line list injected into its
prompt: it can call `list_product_types` and `list_product_lines` at session start, and
the rejection response supplies suggestions.

`reorganize --dry-run` should also list any type folder that does not yet exist on the
share as a "new top-level folder" (agreed as a second safety net). `reorganize` is a
CLI-only verb and is not exposed through the MCP session (see `intent.md`), so this
dry-run listing is read by the user at the terminal, not by the LLM.

### Folders are derived, not stored

The parent folder of a file is derivable from `(root_id, relative_path)`, so it has no
column of its own. Groupings are never asserted by the schema: no `group` table or
column exists, and `scan` does not propose one (see "Folder structure as evidence" in
`intent.md`). The LLM finds folder-level batches through `list_unfiled`, and records its own judgment through `update_product`, which accepts
many files per call.

### Product columns

`product` has `name` (identity, unique within its line) plus nullable `publisher`,
`year`, `artists`, and `description`. There is no separate `title` (it would duplicate
`name`) and no `identification_method`. v1's enum was needed when several commands
created products; here the LLM is the only writer, so most values would be
`llm_judgment`, and the rest would be unverifiable self-claims. The basis for a decision
is recoverable from the evidence tables.

### Names and folder names

Names are stored as given. The path function sanitizes them deterministically for the
filesystem (illegal SMB/Windows characters, trailing dots, length). Because two
different names can sanitize to the same folder ("Foo: Bar" and "Foo- Bar"),
uniqueness is checked on the **sanitized** form within the parent at `update_product`
time, and the error names the colliding existing entry. Nothing derived is stored.

### Disposition and its invariant

`disposition` is as in `intent.md` (`unfiled`, `keep`, `duplicate`, `superseded`,
`discard`), now ratified. The single constraint is that **`keep` requires a
`product_id`**. Other dispositions may keep theirs: a superseded file usually belongs
to the product it was an older edition of, and linking it lets a product report list
its superseded versions. `reorganize` can trust `keep` without re-checking.

### Target path is computed, not stored

One function derives a file's target
`library/<type>/<line>/[<product>/]<filename>` from the file, product, line, and type.
`reorganize` and the pending-change count both call it. A stored target would go stale
whenever a product is promoted or a line is renamed, and each such change would have to
touch every affected file. The cost is that the read-only SQL tool cannot see targets,
so the pending count is a report field and `reorganize --dry-run` is the preview.

The function needs the product's file count for the single-file rule. **Only files
with `disposition = keep` and that `product_id` count**, because only they occupy the
product folder. Consequence: superseding one of a product's two kept files drops it to
one kept file, and the survivor moves up into the line folder on the next
`reorganize`.

### Trash destinations

A non-kept file's destination is `.trash/<bucket>/<root id>-<root folder name>/<original
relative path>`, with buckets `duplicates`, `superseded`, and `discarded`. The original
path is preserved so nothing collides, behind the root component so two dumps holding the
same relative path stay apart. A file already inside `.trash/` only swaps its bucket, so
the location is stable: applying the function to its own result changes nothing, and a
file in the right bucket is never pending. `pending_changes` and `reorganize` both use
`desired_trash_path`.

### Duplicates and moved files

- `duplicate_of_id` links a duplicate to its original. A library-root copy always wins:
  a staging file matching a library file is the duplicate. If both are in staging, the
  earlier-scanned wins. `scan` sets `duplicate_of_id` and `disposition = duplicate`
  together.
- The file row has a nullable `missing_since`. `scan` lists every reachable root and
  marks absent paths missing *before* it processes any file, so a file moved by hand
  (within a root or across roots) meets its old row already marked missing. A later hash match against a missing row is a **move**: the row's
  path is updated, `missing_since` is cleared, and product and disposition are kept. A
  match against a row whose path still exists is a true duplicate. If a root is
  unreachable (share offline), `scan` does not mark its files missing.

### Roots

`root` has `id`, `kind` (`library` or `staging`), `path` (location as mounted, unique),
an optional `label`, `created_at` (when it was registered), and a nullable
`last_scanned_at`. `init` enforces
exactly one `library` root. `add-source` inserts a `staging` row, refuses a path nested
inside (or containing) an existing root so that no file can belong to two roots, and
does not scan.

**`.trash/` lives under the library root**, holding `duplicates/`, `superseded/`, and
`discarded/`. There is one place to empty by hand. `scan` neither walks `.trash/` nor marks rows
under it missing, but trashed files keep their rows, so they stay in the hash join: a fresh copy of a discarded or superseded file in a later
dump is flagged `duplicate` rather than re-raised as a new question (the property
`intent.md` requires of superseding). Trashing a file from a staging root crosses
roots: a rename if both are on the same volume, otherwise a copy that `reorganize` must
verify (by hash) before deleting the source.

### File columns

| Column | Notes |
|---|---|
| `id` | Integer primary key (the LLM passes file ids to `update_product`). |
| `root_id`, `relative_path` | Unique together. Filename and parent folder are derived. |
| `size_bytes`, `mtime` | Filesystem stat, used by the skip rule. `mtime` is whole seconds: SMB timestamp granularity varies, and a sub-second mismatch would force endless rescans. |
| `mime_type`, `media_type` | As in v1. `media_type` is the `rpg_librarian_tools` enum, stored as tolerant text. |
| `sha256` | Indexed, not unique. Nullable, as are `mime_type` and `media_type`, so a row can exist and carry `error` rows before extraction has succeeded. |
| `disposition` | Default `unfiled`. |
| `product_id`, `duplicate_of_id`, `missing_since` | As described elsewhere in this document. |
| `created_at`, `last_seen_at` | `created_at` is when the file was first seen (there is no separate `first_seen_at`). `scan` sets `last_seen_at` when it finds the file present; `reorganize` sets it after a move. There is no separate `last_verified`: it would blur the meaning of `last_seen_at`. |

### Scan skip rule

- **Skip** a file when `(root, path)` exists and both size and mtime match the stored
  values. Update `last_seen_at` and clear `missing_since`.
- **Otherwise** treat it as changed: recopy, rehash, and replace its metadata, text,
  and evidence rows.
- **If the hash changed**, reset `disposition` to `unfiled` and clear `product_id` and
  `duplicate_of_id`. Different content at the same path invalidates the earlier
  judgment.

`reorganize` applies the same size+mtime check before moving a file, and flags rather
than clobbers on mismatch (see `intent.md`).

### Per-media metadata tables

v1's columns carry over unchanged, one row per file with `file_id` as the primary key,
all columns nullable. They were built from what `scan` can extract, and no LLM judgment
needs a field they lack.

| Table | Columns |
|---|---|
| `file_metadata` (embedded properties, any media) | `title`, `artist`, `publisher`, `copyright` |
| `pdf_metadata` | `page_count`, `is_encrypted`, `needs_password`, `has_extractable_text`, `likely_scanned`, `likely_image_only` |
| `image_metadata` | `width`, `height`, `has_alpha`, `pixel_count` |
| `audio_metadata` | `genre`, `duration_seconds` |
| `video_metadata` | `duration_seconds`, `width`, `height`, `has_audio` |
| `mesh_metadata` | `bounding_box_x`, `bounding_box_y`, `bounding_box_z`, `surface_area`, `unit` |

`pixel_count` is `width × height` and redundant, kept so that "find large images" is a
simple indexed comparison.

### Product line aliases

`product_line_alias` has `id`, `product_line_id`, and `alias`. A name given to
`update_product` is matched against line names and aliases within the given type,
ignoring case and collapsing whitespace. An alias may not equal any line name or other
alias in the same type. The database enforces uniqueness on `(product_line_id, alias)`;
the cross-line check runs in code at write time, since the alias row does not carry the
type. Products get no aliases: they are far more numerous, and the near-match warning
already covers naming variants.

### Evidence attaches to files only

`enrich` runs before any product exists, because grouping is the LLM's judgment and
happens afterward, so evidence has nothing else to attach to. Each source gets its own
table with one row per file (`file_id` is the primary key), and every table has the same
three columns after the key: `query` (what was asked), `results` (a JSON list of what
came back), and `fetched_at`. The tables are `dtrpg_result` (top five products: id,
title, description, publisher, authors, game system), `rpggeek_result` (up to five
candidates; the first, and any other whose name equals the query, up to three, also carry
description, systems, categories, designers, and publishers), `isbn_result` (at most one record, with the provider that found it), and
`google_search_result` (below). A query that finds nothing still writes a row with
empty `results`, so the file is not asked again; a failure writes an `error` row and no
evidence row, so it is retried. Product-level facts (publisher, year, artists,
description) are written onto the product by the LLM using that evidence. A shared
polymorphic evidence table was rejected: it gives up foreign-key integrity for a case
that does not arise.

Evidence is dropped when a file's content changes (a new hash), and kept across a
rescan that finds the same bytes.

**Catalog searches use a query ladder.** DriveThruRPG and RPGGeek match on *every*
word, so a query padded with an author or a generic folder ("Fasano Blood And Bone Core
Rules") finds nothing where the bare product name ("Blood and Bone") finds it. Both
sources therefore try, in order and stopping at the first that returns results: the
embedded title, the filename stem, then each ancestor folder from the top down, at most
four requests per file. RPGGeek tries an identified ISBN first. The query that produced
the results (or the last one tried) is stored. Google, which tolerates extra words,
keeps the single rule below.

### Google search results

A simple Google search is one more `enrich` source, fetched through Serper.dev, so the
results are Google's. `google_search_result` has one row
per file: the `query` used, `results` as a JSON list of the top five hits (title, URL,
snippet), and `fetched_at`. A file whose query returns nothing still gets a row, so it
is not queried again. The query is built deterministically (an identified ISBN, else
the embedded title, else the filename stem with its parent folder name) and stored with
the results. Like all evidence it attaches to the file only and is candidate evidence for
the LLM, never an asserted identification.

### Extracted text

`scan` keeps a bounded sample, not full text. The bounds are v1's, hard-coded in
`packages/rpg-librarian-tools/src/rpg_librarian_tools/_text_extraction.py`:

- Text: first 5 pages plus last 2. A page with a real text layer is read directly; only
  pages without one are OCR'd. Bounding the sample also bounds OCR, the most expensive
  step in `scan`.
- Barcode: first 2 pages plus the last page.

The sample is stored as JSON keyed by page number, as in v1. There is no settings table
and no recorded sample size, so changing a constant does not trigger a rescan; the
remedy is v1's `clear-metadata` command. The cost of the choice: raising the sample
size later means rereading affected files from the share.

v1's single `PdfContents` table is split in two:

| Table | Holds | Written by |
|---|---|---|
| `file_text` | `barcode`, `isbn`, `issn`, page-keyed sample text | `scan` |
| `file_text_analysis` | `description`, `possible_system` | `enrich` |

This matches the intent's separate `scan` and `enrich` verbs, which fail differently:
a failed LLM call leaves no second row, and the scan output is never in doubt. "Needs
enrichment" becomes the absence of a `file_text_analysis` row for a file that has a
`file_text` row. A file whose sampled text is empty gets a row with null fields without
an LLM call, recording that it was considered.

### Errors and review flags

Both v1 tables are kept, with `entry_id` becoming `file_id` and stages becoming the
new verbs and their sub-steps.

- `error`: one row per `(file_id, stage)`, overwritten on retry; a transient failure
  log.
- `review_flag`: the LLM's "defer rather than guess" queue, with a `reason`, at most one
  open flag per file, and resolved flags kept with `resolved_at` and `resolution_note`
  as decision history. It matters more here than in v1: the dump folder is the
  worklist, and a file the LLM looked at and could not place would otherwise look
  identical to one it has not reached, so every session would re-read it. `review_flag`
  is a separate table so the ratified `disposition` enum is untouched.

## The MCP surface over the schema

### `update_product`

One call is per product and carries files by id. Working parameter names:

```
update_product(
  file_ids: [int],            # required, many per call
  disposition: keep | superseded | discard | unfiled,
  product_type, product_line, product,   # required when disposition = keep
  product_metadata?: {publisher, year, artists, description},
  create_line?: bool, create_type?: bool,
  aliases?: [str],            # with create_line, or to add to an existing line
  review_flag?: reason, note?: str
)
```

- **Dispositions the LLM writes:** `keep`, `superseded`, `discard`, and `unfiled` (to
  undo). `duplicate` is written only by `scan`.
- **`keep`** requires type, line, and product, which enforces the `product_id`
  invariant at the boundary. **`superseded`** takes the coordinates optionally, so the
  file stays linked to the product it was an older edition of.
- **`review_flag`** is mutually exclusive with `keep`, `superseded`, and `discard`. It
  leaves the file `unfiled` and opens a flag. A later call with a real disposition
  resolves the open flag automatically, recording `note` as the resolution note.
- **All-or-nothing:** one call is one transaction. If any file is invalid nothing is
  written, and the response names the failing file and the reason. Partial success
  would leave the LLM guessing what landed.
- **Rules settled while building it:** `unfiled` clears the product link; `discard` and
  `unfiled` take no coordinates; a review flag leaves the file's disposition unchanged
  (and, like coordinates, cannot be combined with a disposition); an automatic
  `duplicate` or a file missing from the share cannot be filed (the error names the
  original, or says to rescan); a type is checked for sanitized-folder collisions like
  lines and products; at most 500 files per call.
- **Returns** the resolved product, line, and type; which entities were created; any
  near-match warnings; and the folder the product would be filed in, computed by the
  path function so the LLM sees the outcome without a separate read.

### Reads

Eight read tools. Names and returned fields are working names; exact response shapes
are settled at implementation time.

- **`report_file`, `report_product`, `report_line`** each return a structured summary.
  `report_file` includes folder-relative context, embedded and per-media metadata, the
  **text-analysis hint** (`description` and `possible_system`, or null when the file has
  none), all evidence, any error rows, and any open review flag. It does **not** include
  the sampled page text: a model already read it, and the hint is what the session
  needs. `report_product` lists its files compactly (id, path, media type, disposition,
  hint) with the line and type. `report_line` lists its products and aliases.
- **`list_unfiled`** is the worklist. With no folder it returns folders that hold
  unfiled files, with counts and the root each is in. With a folder it returns that
  folder's own unfiled files (id, filename, media type, size, the text-analysis hint)
  plus its subfolders with counts, so a session works one folder at a time. Files
  already resolved never appear: `duplicate`, missing, and any file with an **open
  review flag**, so a file the LLM deferred is not re-read every session.
- **`list_product_types`** returns each type with counts of lines, products, and kept
  files. **`list_product_lines`** returns lines with their type, aliases, and product
  count; an optional case-insensitive `search` matches names and aliases, so the LLM
  finds "D&D 5e" as "Dungeons & Dragons" before it creates a second line.
- **`describe_schema`** lists tables and columns and ships a few named example queries
  (files needing enrichment, open review flags). It marks `file_text.sample_pages` as
  not for querying. **`query`** runs read-only SQL for anything else. It is not
  column-restricted, so it *can* return `sample_pages`; keeping that out of sessions
  is the tool description's job, not the database's.
- **Pending changes:** every report response carries a top-level `pending_changes`
  field, computed by the path function over files whose current location differs from
  their target, with a breakdown by disposition. This is what tells the user when to
  run `reorganize`.

## Open

Nothing remains open in the schema design. Exact field names in the report responses
are settled at implementation time. `intent.md` has no open questions either; the ones
it carried (deterministic grouping, throughput, what triggers `reorganize`) are settled
there.
