# Metadata Model Plan

Design decisions for extracting and storing file/product metadata, reached
via brainstorm on 2026-07-28. This captures the model shape only — no
implementation yet.

## Core Split: Raw vs. Curated

Two tiers with different trust levels and lifecycles:

- **Raw metadata** — untrusted, machine-derived signal, one record per
  `(entry, source)`. Never overwritten across sources; a file's own embedded
  metadata, an ISBN lookup, and an RPGGeek lookup are each kept
  independently, even when they disagree.
- **Curated metadata (`Product`)** — the current best answer, produced by
  judgment (LLM or human), used for folder organization.

Rationale: `Product` is validated and drives real filesystem actions, so it
can't just be "whatever the file said." But raw signal must survive even
after curation, so re-curation is never blocked on re-running extraction/OCR.

## Raw Metadata: Anchored on `Entry`, Not `Product`

All raw metadata (both file-extracted and externally-looked-up) is keyed off
`entry_id`, never `product_id`.

Reason: `Entry` rows exist as soon as sync runs. `Product` rows only exist
after identification — a judgment step that may not have happened yet, and a
lookup (e.g. parsing an ISBN out of a specific PDF) is often what *produces*
the identification, not something that can wait for it. Keying lookups to
`product_id` would invert the real flow.

## Raw Metadata: One Table Per Source, Not a Shared `source` Column

Each source (file's own embedded metadata, RPGGeek lookup, ISBN lookup,
DriveThruRPG lookup, ...) gets its own dedicated table with its own real
columns, rather than one shared-schema table with a `source` discriminator
column.

Reason: different sources return genuinely different field vocabularies
(RPGGeek might give genre/system-adjacent data; an ISBN lookup gives
title/publisher/year; file-embedded metadata gives whatever the format
happens to expose). Forcing them into one shared schema recreates the same
sparsity problem as a wide table across media types — just one level up.

Each such table:
- PK is `entry_id` (0..1 relationship from `Entry`).
- Re-running that source **upserts** the existing row (matches the
  `EntityBase.updated_at` / `onupdate` convention already used by `Entry`
  and `Product`). Same-source drift over time is noise correction, not a
  "keep every version" case — only cross-source disagreement needs to be
  preserved permanently.

`FileMetadata` (the file's-own-embedded-metadata source) is a normal
example of this pattern — kept separate from `Entry` itself, since `Entry`
stays the lean, always-populated filesystem-identity record (hash, size,
path, mime, `media_type`), while metadata extraction is best-effort,
frequently absent, and independently re-run over time.

MCP listing tools (`list_directory_entries` etc.) will need to `LEFT JOIN`
`FileMetadata` and the relevant per-type table onto `Entry` to report this
data — no model changes required for that, just extra joins.

## Raw Metadata: Split Generic vs. Type-Specific Tables

Generic fields (title, artist, publisher) and media-type-specific fields
(page_count, bounding_box, duration, ...) live in **separate tables**, not
one combined row:

- `FileMetadata(entry_id PK, title, artist, publisher, ...)` — generic,
  applies to any media type.
- One side table per media type — `PdfMetadata(entry_id PK,
  page_count, ...)`, `MeshMetadata(entry_id PK, bounding_box_min,
  bounding_box_max, ...)`, `AudioMetadata(entry_id PK, genre, ...)`,
  etc. — populated only for entries of the matching `media_type`.

Reason: `media_type` is a single value per `Entry` (already a hard
discriminator via `TolerantMediaType`), so a combined table would have every
type-specific column NULL except the handful matching that entry's type,
and every new media type added would widen an already-sparse table. Splitting
means adding a new media type is purely additive (new table + migration),
and queries only join the type table they actually need.

**Genre is audio-specific**, not generic — it doesn't apply to a PDF
rulebook or an STL mini, so it lives on `AudioMetadata`, not
`FileMetadata`.

## `Product`: Curated Fields

- `title`, `description`, `artists`, `publisher`, `year` — all **nullable**.
  A `Product` can be created from a weak identification method that doesn't
  know everything yet (e.g. an LLM guesses a title from a filename but has
  no publisher). `description` in particular is never available from
  extraction — it always requires an external lookup — so requiring it
  would block folder organization on the slowest, least-reliable field.
- `system` (new field) — **free text**, not a closed enum, with a defined
  sentinel constant (e.g. `Product.UNKNOWN_SYSTEM = "unknown"`) for the
  unidentified case. RPG systems are an open-ended, ever-growing set
  (indie/small-press titles constantly), so a closed enum would require a
  code change + migration every time the library gains a product for an
  unseen system. **`system` is curation-only** — it is almost never present
  in raw file/lookup metadata, so no raw table carries it; it's inferred by
  the curator (LLM/human) from context.
- `identification_method` (new field) — a **single, closed `StrEnum`**
  (e.g. `isbn_match`, `rpggeek_match`, `drivethru_match`,
  `filename_heuristic`, `llm_judgment`, `manual`), consistent with the
  existing `ErrorStage` enum pattern. This is **product-level, not
  per-field** — it answers "how confident are we that this Product is
  correctly identified overall," not "where did each individual field come
  from."
  - This doubles as the review-queue mechanism already described in the
    architecture notes ("no forced placement... flagged for review"): a
    tool can trivially query "every product identified by
    `filename_heuristic` or `llm_judgment`" as the review queue, with no
    separate `needs_review` flag required.

## Type-Specific Field Lists

- **Image**: `width`, `height`, `has_alpha`, `pixel_count` (`width * height`
  — derivable, but stored as given).
- **3D mesh**: `bounding_box_x`, `bounding_box_y`, `bounding_box_z`,
  `surface_area`, `unit` (mm, cm, inch, ...). `unit` applies to *both* the
  bounding box dimensions and `surface_area` — a single unit-relative value
  set per row, no fields with a unit baked into the name (no `_cm` suffix).
- **PDF**: `page_count`, `is_encrypted`, `needs_password`,
  `has_extractable_text`, `likely_scanned`. `is_encrypted` and
  `needs_password` are independent-but-related booleans, not redundant — a
  PDF can be permissions-encrypted without requiring a password to open
  (`is_encrypted=true`, `needs_password=false`); `needs_password=true`
  implies `is_encrypted=true`.
- **Video**: `duration_seconds`, `width`, `height`, `has_audio`.
- **Audio**: `duration_seconds` only.
- **Vector**: no type-specific table — generic `FileMetadata` is sufficient
  for now.

## Summary of Table Shapes

```
Entry (existing)
  id, parent_path, filename, sha256, size_in_bytes, mime_type, media_type,
  product_id (nullable FK -> Product)

FileMetadata            -- one row per Entry, from the file's own embedded metadata
  entry_id (PK, FK -> Entry)
  title, artist, publisher, ...

PdfMetadata        -- one row per Entry where media_type == pdf
  entry_id (PK, FK -> Entry)
  page_count, is_encrypted, needs_password, has_extractable_text,
  likely_scanned

MeshMetadata       -- one row per Entry where media_type == mesh
  entry_id (PK, FK -> Entry)
  bounding_box_x, bounding_box_y, bounding_box_z, surface_area, unit

AudioMetadata      -- one row per Entry where media_type == audio
  entry_id (PK, FK -> Entry)
  genre, duration_seconds

ImageMetadata      -- one row per Entry where media_type == image
  entry_id (PK, FK -> Entry)
  width, height, has_alpha, pixel_count

VideoMetadata      -- one row per Entry where media_type == video
  entry_id (PK, FK -> Entry)
  duration_seconds, width, height, has_audio

(no table for media_type == vector; FileMetadata is sufficient)

(future) RpggeekLookup, IsbnLookup, DrivethruLookup, ...
  entry_id (PK, FK -> Entry)
  <source-specific columns, e.g. title, publisher, system-hint, description>

Product (existing, revised)
  id, title (nullable), description (nullable), artists (nullable),
  publisher (nullable), year (nullable),
  system (str, sentinel default = unknown),
  identification_method (StrEnum)
```

## Open Items (Not Yet Decided)

- Whether/how the `Error` table should track failures per-source and
  per-type now that extraction has more moving pieces (currently only has
  `ErrorStage.populate_file_data`).
- How curation reconciles conflicting raw values across multiple entries
  within the same product (e.g. two PDFs in one product folder with
  different embedded titles) — left to the judgment tool, not modeled in
  the DB.
