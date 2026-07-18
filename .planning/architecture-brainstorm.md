# rpg-librarian-mcp Architecture

## Overview

`rpg-librarian-mcp` is a single MCP server that exposes an RPG media library's
catalog — and the tools to build and maintain it — to an LLM (Claude Code)
acting as the orchestrating "integration code." It replaces the orchestration
layer of the existing `rpg-librarian` CLI project (the `commands/` pipeline)
while reusing its mechanical extraction and lookup logic. The server is
portable: install it once, then run it against any library by starting
Claude Code in that library's root directory.

## Key Concepts

- **Library root** — the top-level directory containing the RPG content
  (e.g. `c:\rpg\`). The server resolves everything relative to the directory
  Claude Code was launched from (`cwd`); there is no hardcoded or configured
  path.
- **Catalog** — the SQLite database (`.catalog/catalog.db`, under the library
  root) that is the single source of truth for every file in the library.
  Not checked into git; it is personal data with its own backup story, not
  source-controlled code.
- **Catalog entry** — one row per file: media type, hash, extracted metadata,
  OCR text (where applicable), classification, and provenance of how each
  field was determined.
- **Product** — a collection of files sold/distributed as a unit (a
  rulebook, a map pack, a mini set). The unit of organization and
  classification is the product, not the individual file. Products are
  generally folder-grouped.
- **Mechanical tools** — tools with no judgment content: hashing, media-type
  detection, metadata extraction (PDF/audio/video/mesh), ISBN parsing,
  filesystem walking. Ported from the existing `rpg-librarian` codebase
  largely as-is.
- **Judgment tools** — tools where the calling LLM's reasoning does the work:
  product identification, system/category classification, resolving
  ambiguous matches, reorganization decisions.
- **Inbox** — a default staging location for newly acquired content, used
  for the common "I bought/downloaded something" case. Tools also accept an
  arbitrary path for one-off ad-hoc drops.

## Flows

### First run in a new library
1. User starts Claude Code with `cwd` set to the library root.
2. User asks Claude Code to sync/initialize the catalog.
3. The sync tool creates `.catalog/catalog.db` if it doesn't exist, walks
   the filesystem, and adds an entry for every file found. No separate init
   step is needed — sync handles both bootstrap and ongoing reconciliation.

### Ongoing reconciliation (existing library)
1. User asks Claude Code to sync the catalog.
2. The sync tool walks the filesystem, adds entries for new files, and
   flags/cleans entries whose files no longer exist (no dangling orphans).
   This is a coarse, server-side batch operation — the LLM does not iterate
   per file.

### New content ingestion (purchase or download)
1. New content lands in the inbox (or an arbitrary path is given directly).
2. Claude Code processes it using the fine-grained tools: detect media
   type, extract metadata, parse/look up ISBNs, search external sources for
   product identification.
3. Where identification is ambiguous or a folder contains multiple
   distinct products, Claude Code reasons about the split using the
   fine-grained, per-folder-chunked tools.
4. Claude Code places the identified product into the organized tree and
   commits the resulting catalog entries/product record.

### Reorganization / classification of the existing library
1. Judgment tools are invoked in folder-scoped chunks (not one giant batch,
   not one file at a time) so decisions stay reviewable.
2. Each product is classified (system, content role) and identification
   details are recorded.
3. Anything not confidently placeable is left untouched and flagged for
   review, rather than force-placed.

### Full-text search
1. OCR'd PDF text is indexed in a SQLite FTS5 virtual table, keyed by
   catalog entry id.
2. A `search_text` tool queries the FTS5 index directly, returning matching
   entry ids — no per-file scan of loose text files.

### Migration from the existing `rpg-librarian` catalog
1. A one-time script reads the old `index.json` and `products.json` and the
   old loose-file OCR text fragments directory.
2. It populates the new SQLite schema (catalog entries, products, FTS5 text
   index), preserving all previously resolved metadata (ISBN lookups, LLM
   identifications, OCR text) so none of that prior work is redone.

## Behaviors & Rules

- **Granularity split**: bulk mechanical work (hashing, OCR, filesystem
  sync) runs entirely server-side in one tool call and returns a summary;
  Claude Code never iterates per file for this kind of work. Judgment work
  (classification, identification, reorg decisions) is chunked **per
  folder** when chunking is needed, so it stays within a reviewable session
  and aligns with how products are already grouped.
- **Fine-grained tools do double duty**: the same per-item tools
  (`detect_media_type`, `extract_metadata`, `lookup_isbn`, etc.) back both
  the internals of bulk batch tools and the interactive ingestion flow for
  new content — they are not single-purpose.
- **Single server, single process**: all tools — catalog/product data,
  local file mechanics, and external lookups (ISBN/RPGGeek/DriveThruRPG/STL
  marketplaces) — are exposed from one unified MCP server, not a
  constellation of separate servers. This trades away per-service
  isolation (e.g. sharing just the catalog tools without external-lookup
  API dependencies) for one thing to start/stop and one thing to hand to
  someone else.
- **Database is never version-controlled.** The repo holds code only. The
  catalog database lives under `.catalog/` in the library root, wherever
  that root happens to be, and is excluded from git entirely.
- **Portability**: the server has no fixed notion of "the library" baked
  in. The library root is wherever Claude Code's `cwd` is when it's
  launched; running the same installed server against a different `cwd`
  operates on a different, independent library.
- **No forced placement**: reorganization never guesses a product into a
  folder just to make a run "complete" — low-confidence cases are left in
  place and reported.

## Open Questions

- Concrete MVP tool list and naming.
- SQLite schema shape (table/column design for catalog entries, products,
  and the FTS5 text index).
- Tech stack/framework choice for building the server (e.g. which Python
  MCP SDK/framework).
