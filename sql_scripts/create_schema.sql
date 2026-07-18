-- rpg-librarian-mcp catalog schema
-- Run with foreign_keys enforcement on (set per-connection in application code too):
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- schema_meta: single-row-per-key bookkeeping table, so future schema changes
-- can be detected/migrated rather than guessed at.
-- ---------------------------------------------------------------------------
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1');

-- ---------------------------------------------------------------------------
-- products: one row per product (a book, map pack, mini set, ...), generally
-- folder-grouped. Populated/refined by identification and classification
-- tools; a product with no successful lookup yet has no_match = 0 and most
-- nullable fields empty until a match is found.
-- ---------------------------------------------------------------------------
CREATE TABLE products (
    id           TEXT PRIMARY KEY,
    folder       TEXT NOT NULL UNIQUE,
    title        TEXT,
    publisher    TEXT,
    author       TEXT,
    url          TEXT,
    description  TEXT,
    -- Tabletop system/ruleset the product belongs to, e.g. "D&D 5e"; NULL for
    -- system-agnostic content.
    system       TEXT,
    -- Content role within a system tree: Core Rules / Adventures and
    -- Scenarios / Settings and Supplements / GM and Player Aids / Extras.
    category     TEXT,
    -- Provenance: how title/publisher/etc. were determined (e.g. "isbn_lookup",
    -- "llm_lookup"). NULL means not yet identified.
    source       TEXT,
    -- True once a lookup has been tried and failed, so later passes don't retry.
    no_match     INTEGER NOT NULL DEFAULT 0 CHECK (no_match IN (0, 1)),
    -- JSON array of error strings encountered while processing this product.
    errors       TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_products_system   ON products (system);
CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_no_match ON products (no_match);

-- ---------------------------------------------------------------------------
-- entries: the master table, one row per file. Holds file mechanics (hash,
-- size, media type) and the universal identity fields (old BaseMetadata) that
-- apply regardless of media type. Media-type-specific fields live in the
-- side tables below, one row per entry in exactly one of them, matching
-- media_type.
-- ---------------------------------------------------------------------------
CREATE TABLE entries (
    id           TEXT PRIMARY KEY,
    filepath     TEXT NOT NULL UNIQUE,
    filename     TEXT NOT NULL,
    extension    TEXT,
    -- Immediate containing directory of filepath. A strong identity signal
    -- on its own (folder name is often the product or publisher name, e.g.
    -- DriveThruRPG\<Publisher>\<Product>\...) and the grouping key product
    -- discovery uses to cluster loose files with no product_id yet.
    parent_folder TEXT,
    -- One level further up. Weaker/less consistent a signal than
    -- parent_folder (library folder depth varies a lot by branch), kept as
    -- extra context for identification but not a query target.
    grandparent_folder TEXT,
    size_in_bytes INTEGER NOT NULL,
    -- Unix timestamp of the file's last-modified time at last sync. Cheap
    -- change-detection heuristic so a sync doesn't have to rehash every file
    -- to notice nothing changed.
    mtime        REAL,
    sha256       TEXT NOT NULL,
    mime_type    TEXT,
    media_type   TEXT NOT NULL CHECK (
        media_type IN ('audio', 'video', 'image', 'vector', 'pdf', 'mesh', 'text', 'unknown')
    ),
    product_id   TEXT REFERENCES products (id) ON DELETE SET NULL,

    -- Universal identity fields (old BaseMetadata) -- apply to any media type.
    artist       TEXT,
    title        TEXT,
    publisher    TEXT,
    copyright    TEXT,
    genre        TEXT,
    -- Tabletop system/ruleset, e.g. "D&D 5e"; NULL if unknown/system-agnostic.
    system       TEXT,
    description  TEXT,
    url          TEXT,
    isbn         TEXT,
    issn         TEXT,
    barcode      TEXT,
    -- Provenance: how the identity fields above were found (e.g. "isbn_lookup",
    -- "llm_lookup"). NULL means not yet identified.
    source       TEXT,
    -- True once an LLM lookup has been tried and failed, so later passes
    -- don't retry.
    llm_no_match INTEGER NOT NULL DEFAULT 0 CHECK (llm_no_match IN (0, 1)),

    -- Provenance for an external-catalog fuzzy match (e.g. "loot_lookup"),
    -- distinct from `source`: tracks that a match pass has already run,
    -- independent of what fields it filled in.
    match_source TEXT,
    -- What the match pass matched this entry to, e.g. the matched product's title.
    match_found  TEXT,

    -- JSON array of error strings encountered while processing this file.
    errors       TEXT NOT NULL DEFAULT '[]',

    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_entries_sha256        ON entries (sha256);
CREATE INDEX idx_entries_media_type    ON entries (media_type);
CREATE INDEX idx_entries_product_id    ON entries (product_id);
CREATE INDEX idx_entries_publisher     ON entries (publisher);
CREATE INDEX idx_entries_system        ON entries (system);
CREATE INDEX idx_entries_isbn          ON entries (isbn);
CREATE INDEX idx_entries_parent_folder ON entries (parent_folder);

-- ---------------------------------------------------------------------------
-- Media-type-specific side tables. Each is a strict 1:1 extension of
-- `entries`, holding only fields meaningful for that media type. A given
-- entry has a row in at most one of these, matching entries.media_type.
-- ---------------------------------------------------------------------------

CREATE TABLE pdf_metadata (
    entry_id             TEXT PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    page_count           INTEGER,
    is_encrypted         INTEGER CHECK (is_encrypted IN (0, 1)),
    needs_password       INTEGER CHECK (needs_password IN (0, 1)),
    has_extractable_text INTEGER CHECK (has_extractable_text IN (0, 1)),
    likely_scanned       INTEGER CHECK (likely_scanned IN (0, 1))
);

CREATE TABLE image_metadata (
    entry_id    TEXT PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    width       INTEGER,
    height      INTEGER,
    pixel_count INTEGER,
    artists     TEXT,
    copyright   TEXT,
    has_alpha   INTEGER CHECK (has_alpha IN (0, 1))
);

-- media_type = 'vector'
CREATE TABLE svg_metadata (
    entry_id TEXT PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    width    REAL,
    height   REAL,
    units    TEXT,
    view_box TEXT
);

CREATE TABLE audio_metadata (
    entry_id TEXT PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    duration REAL
);

CREATE TABLE mesh_metadata (
    entry_id            TEXT PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    bounding_box_x_mm   REAL,
    bounding_box_y_mm   REAL,
    bounding_box_z_mm   REAL,
    surface_area_cm2    REAL,
    unit                TEXT
);

CREATE TABLE video_metadata (
    entry_id        TEXT PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    duration_seconds REAL,
    width           INTEGER,
    height          INTEGER,
    has_audio       INTEGER CHECK (has_audio IN (0, 1)),
    title           TEXT,
    artist          TEXT,
    comment         TEXT
);

-- ---------------------------------------------------------------------------
-- entry_text: OCR'd text, one row per entry that has it (PDFs, mainly).
-- Standalone FTS5 table -- the text is stored only here, nowhere else -- with
-- entry_id as a plain (unindexed by FTS, but filterable) column rather than
-- tied to entries' rowid, since entries.id is an application-assigned TEXT id
-- rather than an integer rowid.
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE entry_text USING fts5(
    entry_id UNINDEXED,
    content
);
