# Intent: refactor rpg-librarian to a new app

Replace the existing `packages/rpg-librarian-mcp` with a ground-up application in
`apps/` (src layout) built around a different division of labor: deterministic bulk
work runs in a CLI that spends no orchestration tokens, and an LLM session does only
the judgment work, writing its conclusions to a catalog database that the filesystem
is then made to match.

The catalog's concrete design lives in [catalog-schema.md](catalog-schema.md), which
supplements this document; where the two differ, the schema document is newer. This
document has been reconciled with it, and points there instead of repeating it.

## Intended outcome

A single application, runnable either as a FastMCP stdio server or as a CLI, that
incrementally turns unorganized dumps of RPG content on a network share into an
organized library — without the LLM ever reading files off the share or performing
work that deterministic code can do.

## Scope

In scope:

- New app under `apps/`, src layout. Reusable code may be moved over from the
  existing packages where it helps.
- A new catalog database schema, designed as part of this refactor (see
  [catalog-schema.md](catalog-schema.md)).
- Both entry points (MCP stdio server, CLI) in the same app.

Out of scope / explicitly replaced:

- The current `packages/rpg-librarian-mcp` package is removed, not evolved. Its
  ~23-tool MCP surface, its `ContentRole` / system-specific-vs-agnostic
  organization scheme, and its existing alembic migration chain do not carry
  forward.
- The v1 library `CLAUDE.md` instructions (previously seeded into the library root)
  were removed as not working; a replacement is deferred and is not part of this
  document.

`packages/rpg-librarian-tools` — stateless atomic operations (hashing, OCR, barcode
scanning, media detection, DriveThruRPG and RPGGeek clients) — remains available for
reuse.

## Constraints

- **Content lives on a network share; the database does not.** The library and the
  incoming dumps are share-resident because the content outgrew local disk. The
  SQLite catalog is loaded from the local working directory.
- **The CLI spends no tokens on orchestration or judgment.** The CLI *may* call an
  LLM for extraction-type tasks (summarizing a PDF, guessing a system from sampled
  text, normalizing a name) — those are batch extractions whose results land in the
  database as data. What stays out of the CLI is deciding which files form a
  product, or whether an incoming file duplicates a library one.
- **Share access pattern is copy local → process → delete.** One local copy serves
  all extraction for that file (hash, OCR, barcode, render, embedded metadata)
  rather than traversing the share once per operation.
- **The monorepo root wires up `packages/*` in four places** — `[tool.uv.workspace]
  members`, `[tool.ruff] src`, `[tool.ty.environment] root`, and
  `[tool.pytest.ini_options] testpaths` in the root `pyproject.toml`. An app under
  `apps/` is invisible to the workspace resolver, linter, type checker, and test
  runner until all four are updated. **Partly done:** the root `pyproject.toml`
  includes `apps/*` in the workspace and `apps/rpg-librarian/{src,tests}` in the ruff
  paths, so the app lives at `apps/rpg-librarian`. **Still to do when the app
  skeleton is created:** add `./apps/rpg-librarian/src` and `./apps/rpg-librarian/tests`
  to `[tool.ty.environment] root`, and `apps/rpg-librarian/tests` to pytest
  `testpaths`. They were left out because ty errors on a root that does not exist
  yet. The `packages/*` entries stay until the v1 package is removed.

## Core architectural decision: the database is master

The catalog database is authoritative. The library filesystem is a projection of it.

The LLM session writes product coordinates to the database and performs no file I/O.
A separate CLI true-up (`reorganize`) makes the filesystem match the database.

Reasons this was chosen over having a `move` tool mutate filesystem and catalog
together:

- A remote rename plus a local SQLite commit cannot be one transaction. Under
  DB-master there is no distributed transaction to get right.
- True-up is a **diff between desired and actual state, not a replay of an action
  log**. That makes it idempotent, resumable after a crash or dropped share, and
  free to dry-run. An action log interrupted halfway is ambiguous; a desired-state
  diff is simply re-run.
- The LLM can reorganize large numbers of products at database speed, and mistakes
  are correctable in the database before anything on the share moves.
- Placement rules live in one function instead of in every prompt (see
  "single-file products" below).

Consequence to design for: the filesystem is stale between a session and the next
`reorganize`. Reports should surface a pending-change count so drift is visible.
True-up must also verify the file at the recorded source path (by hash, or
mtime+size) before moving it, and flag rather than clobber on mismatch.

## Organization scheme

`library / product-type / product-line / product / files`

- **product-type** — categorized *by function*: `games`, `maps`, `animated-maps`,
  `soundfx`, `soundtracks`, `handout-art`, `miniatures`, `terrain`, `vtt packs`,
  `system-agnostic-text`. The seed list is a constant in code, and the LLM may add
  types through `update_product` (see [catalog-schema.md](catalog-schema.md)).
- **product-line** — a game (Dungeons & Dragons, Traveller), a 3D model line (Loot
  Studios), a map publisher (2-Minute Tabletop).
- **product** — files that shipped together as one unit: a specific map pack, a
  module with its maps and character sheets, a particular sound-effects collection.

Two placement rules:

1. **Single-file products have no product folder.** A one-PDF product (a core
   rulebook, a standalone adventure) is filed directly in the product-line folder.
   Because the target path is computed from the database, this is a pure function of
   (product-type, product-line, product, file count) — and promotion happens
   automatically if that product later gains a second file.
2. **The product, not the file, is the unit of placement.** Maps, handouts, and
   portraits that shipped as part of a specific adventure stay with that product
   under `games`. Generically branded content ("here are some D&D maps") is a
   product in its own right and belongs in the functional folder — such content is
   usable across systems. Where there is a choice, prefer placing outside `games`.

## MCP tool surface

Small and read-mostly. The five read tools are original requirements, not derived
design: report on a file, report on a product, report on a product line, discover
the database schema, and run read-only queries against it.

A sixth tool in the original requirements — a `move` tool that updated filesystem
and catalog atomically — was **dropped by explicit agreement**. `reorganize`
subsumes it, and the atomicity it promised is not achievable across a network share
anyway (see "the database is master" above).

That leaves one writer, `update_product`, which records product coordinates. It is
the mechanism by which the LLM asserts product-type / product-line / product and
disposition for a set of files. Its creation rules are settled in
[catalog-schema.md](catalog-schema.md): an unknown line or type is rejected with
suggestions unless `create_line` / `create_type` is passed, and an unknown product
name is created with a warning when close to an existing one. The full signature
(files by id, disposition, all-or-nothing transaction, `review_flag`) is in
[catalog-schema.md](catalog-schema.md).

## Working design: catalog and workflow

The following reflects the design as worked out, and is the current direction rather
than a separately ratified decision (except the disposition model, which the user
has ratified; see below).

### One catalog, not two

There is no separate "inbox catalog" merged into a "golden catalog". There is one
catalog spanning multiple registered roots (one library root, any number of staging
roots). An incoming dump is simply the *unfiled region* of that one catalog, and
filing an item means assigning it product coordinates. This removes the merge step
as a distinct subsystem, and makes "do I already have this file?" a hash join rather
than a question posed to the LLM.

### CLI verbs

| Verb | Does |
|---|---|
| `init` | Creates the local catalog, registers the library root |
| `add-source` | Registers a staging root (a dump folder) |
| `scan` | Walks a root recording path/mtime/size; per file copies local, then hashes, detects media, extracts PDF text/OCR, reads barcodes and embedded metadata, then deletes the local copy. Idempotent — skips files unchanged by path+mtime+size. Also hash-joins against the whole catalog to flag exact duplicates. |
| `enrich` | Separate verb because it is rate-limited and fails differently: DriveThruRPG / RPGGeek / ISBN lookups, a simple Google search per file (top five hits stored as candidate evidence), and any LLM extraction |
| `reorganize` | Renders the whole catalog onto the share: moves files to their computed paths, routes non-kept files aside. Supports `--dry-run`. Writes only bookkeeping (current path, `last_seen_at`), never product assignments. CLI-only. |

### Typical flow

1. `init --library <share>/library`, then `add-source <share>/dump_A`.
2. `scan` the dump (idempotent; safe to re-run), then `enrich`.
3. MCP session: the LLM queries unfiled entries, reads reports, groups files into
   products, and calls `update_product` to record product-type / product-line /
   product.
4. `reorganize --dry-run`, then `reorganize`. Files move out of the dump into the
   library. **Whatever remains in the dump folder is exactly what is still
   unfiled** — the folder is a live worklist.
5. Repeat for the next dump. The second and later dumps arrive with exact duplicates
   already flagged by the hash join.

An empty library needs no bootstrap special case: the first dump is just the first
dump. An existing organized library would be scanned the same way, its paths serving
as evidence. If a file is moved by hand on the share, re-scanning re-identifies it
by hash and the next `reorganize` restores it; the `missing_since` mechanism in
[catalog-schema.md](catalog-schema.md) keeps that move from being mislabelled a
duplicate.

### Routing non-kept files (disposition model, ratified)

Nothing in the design above removes a duplicate from a dump folder. The answer,
ratified by the user, is a `disposition` field, written only by `scan` (automatically, on exact
hash match) and by the LLM via `update_product`, and read only by `reorganize`:

| disposition | set by | `reorganize` places the file |
|---|---|---|
| `unfiled` (default) | `scan` | leaves it in place |
| `keep` | LLM | `library/<type>/<line>/[<product>/]` |
| `duplicate` | `scan`, automatically on hash match | `.trash/duplicates/` |
| `superseded` | LLM, on the **older** entry | `.trash/superseded/` |
| `discard` | LLM | `.trash/discarded/` |

Two properties this depends on: duplicates must *leave* the dump folder (otherwise
resolved and unresolved files sit together and the worklist property is lost), and
superseding must never delete a row — the row records that a decision was already
made, so a later scan of the trash folder does not re-raise a settled question.
Disposition is a declared end state, not an action to perform.

No automatic deletion anywhere; trash is emptied by hand. `.trash/` lives under the
library root (see [catalog-schema.md](catalog-schema.md)).

## Settled decisions

| Decision | Reason |
|---|---|
| New app in `apps/`, v1 package removed | v1's scheme and schema are being replaced, not migrated |
| New catalog schema designed in this refactor | The v1 model encodes the old organization scheme |
| One app, two entry points (FastMCP stdio, CLI) | Same catalog logic, different front door |
| MCP surface is the five read tools from the original requirements plus one writer | Read-mostly by design; judgment is the LLM's only job |
| The originally-specified `move` tool is dropped | Explicitly agreed; `reorganize` subsumes it and cross-share atomicity was never achievable |
| Catalog is local; content is on the share | Content outgrew local disk |
| CLI may call an LLM for extraction, never for orchestration or judgment | Keeps token spend proportional to judgment, not file count |
| Copy local → process → delete | One share read serves all extraction for a file |
| Database is master, filesystem is its projection | Removes the impossible atomic-write problem; see above |
| LLM writes only to the database; a CLI true-up moves files | Idempotent, resumable, dry-runnable |
| Product type is categorized by function | Replaces a scheme that mixed media and function axes |
| Single-file products live directly in the product-line folder | Computed from the database, so it needs no rule in the prompt |
| Routing of non-kept files uses a `disposition` field (`unfiled`, `keep`, `duplicate`, `superseded`, `discard`), written by `scan` and the LLM, read only by `reorganize` | Duplicates must leave the dump folder to preserve the worklist property; superseding never deletes a row so settled decisions are not re-raised; disposition is a declared end state, not an action. No automatic deletion; trash is emptied by hand. |
| Product-line gets normalized identity (a table or equivalent) | It is the one coordinate the LLM must match consistently across separate sessions; free-text names would fragment silently. Shape settled in [catalog-schema.md](catalog-schema.md): a `product_line` table unique on (type, name) plus an alias table. |
| The LLM may create product types and lines, via `update_product` flags | Chosen by the user; a type is a top-level folder, so it needs its own deliberate flag. See [catalog-schema.md](catalog-schema.md). |
| No deterministic grouping in `scan`; folder structure is evidence the LLM sees, never a group the app asserts | Real dumps are inconsistently organized and sometimes flat; a wrong group is worse than none. No zip archives are handled: the user unpacks those by hand. |
| Throughput is an accepted limitation, mitigated by folder-at-a-time batching | Speed depends on how folder-structured a dump is; no mechanism is built to remedy flat piles beyond `enrich` evidence |
| `reorganize` is a CLI-only verb, never invocable from the MCP session | Keeps slow share I/O out of tool calls and the LLM out of filesystem writes. The session sees the pending-change count in its reports and tells the user when to run it; `--dry-run` covers previewing. |
| `vtt` is renamed `vtt packs` | The content is token and asset collections for a virtual tabletop, not tabletops themselves |

## Rejected

**Deterministically deriving product type / product line / product from file
metadata.** Rejected on the basis of the user's own trials, which did not achieve
this. The LLM is required for classification. This is recorded so it is not
reopened; note that it does not apply to *exact-hash identity*, which is
deterministic and is used for duplicate detection.

**Deterministic grouping in `scan`** (proposing which files shipped together from
directory adjacency, filename stems, or clustered mtimes). Considered and declined.
The user's dumps are often a publisher/product-line hierarchy with subfolders, but
their accuracy is low and some dumps may be flat piles, so a proposed group would
often be wrong, and a wrong group misleads more than none. Groupings are never
treated as deterministic. Instead the folder path is evidence exposed to the LLM
(see "Folder structure as evidence" below).

## Folder structure as evidence

Incoming dumps often carry a publisher/product-line hierarchy with subfolders, but
inconsistently, and some may be flat. The app does not interpret this. It exposes it:

- The parent folder is derivable from `(root_id, relative_path)`, so no new column is
  needed.
- The LLM can query unfiled files grouped by parent folder, with counts, and work a
  folder at a time. `update_product` accepts many files per call.
- Flat piles fall back to per-file work, using evidence from `scan` and `enrich`
  (ISBN, barcode, DriveThruRPG match, sampled text). Files matching the same
  DriveThruRPG product are a candidate evidence signal, not an asserted group.
- Whether a subfolder such as `.../maps/` belongs to the same product is the LLM's
  judgment.

Every file still passes through an LLM session; throughput is bounded by how
folder-structured a dump is. This is accepted rather than remedied.

## Open questions

None remain in this document or in [catalog-schema.md](catalog-schema.md). Exact
report field names are settled at implementation time.
