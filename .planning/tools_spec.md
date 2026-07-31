# MCP tools — spec

Durable spec for all MCP tools in this project. Goal: give the LLM a way to
update the catalog, check the status of cataloging work, identify what
still needs to be done, and pick a next step.

| Tool | Status |
| --- | --- |
| `update_catalog` | complete |
| `list_directory_entries` | complete |
| `summarize_directories` | complete |
| `list_errors` | complete |
| `run_readonly_query` | complete |
| `get_catalog_schema` | complete |
| `move` | complete |
| `read_pdfs` | complete |
| `search_rpg_geek` | complete |
| `lookup_rpg_geek_product` | complete |
| `search_dtrpg` | complete |
| `lookup_isbn` | complete |
| `update_product` | complete |
| `ingest_external_source` | complete |
| `classify_content_role` | complete |
| `find_duplicates` | complete |
| `remove` | complete |

## Tool 0 — `update_catalog(path, process_recursively=False, force=False)`

**Status: complete.** Implemented in `mcp/update_catalog.py`, backed by
`commands/UpdateCatalogCommand.py`.

```python
async def update_catalog(
    path: Path,
    ctx: Context,
    process_recursively: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Scan a file or directory and update the catalog to match it."""
```

`path` may be a single file or a directory; directories are non-recursive
unless `process_recursively` is set. `force` bypasses the "skip if
unchanged" check and reprocesses every matched file.

Response shape (from `UpdateCatalogResult`, `commands/UpdateCatalogCommand.py:54`):
```json
{
  "scanned": 120,
  "skipped": 80,
  "successfully_processed": 38,
  "removed": 1,
  "errored": 1,
  "errors": [
    {"...": "ProcessingError fields, capped to max_errors (default 50)"}
  ]
}
```

## Read/status tools — design

**Status: complete** for all three tools below, implemented in
`mcp/directory_status.py` (tools 1-2) and `mcp/errors.py` (tool 3). One
cross-cutting fix discovered during implementation: `ParentPathType`'s bind
validation (`model/core.py`) rejects any `parent_path` with fewer than two
parts on *every* bind, including `WHERE` clauses — not just inserts. A
non-recursive query against a shallow path (e.g. `"books"`) would otherwise
crash instead of returning an empty result. `tools/entry_queries.py` adds
`entries_by_parent`/`entry_by_exact_path` helpers that skip the bind
entirely for depth-&lt;2 paths (returning empty/`None`), since no real
`Entry` can have such a `parent_path` anyway. Used by tool 1's non-recursive
branch and by `move`'s file-lookup branch.

`summarize_directories`'s directory-count aggregation ended up done
Python-side (iterate all `Entry` rows, group by `parent_path` in a dict)
rather than the spec's SQL `GROUP BY` with conditional `SUM(CASE ...)` —
`ty` couldn't resolve the SQLAlchemy `case`/`func.sum` overloads against
`sqlmodel`'s typed `select()`, and the Python-side scan matches the
full-table-scan precedent `UpdateCatalogCommand` already uses for deletion
reconciliation. Same performance trade-off, not a correctness change.

`list_directory_entries` adds one field beyond the original response shape:
each file also carries `"cataloged": bool`, distinguishing "never scanned"
from "scanned, no product yet" — both would otherwise show `has_product:
false` indistinguishably, which is the same ambiguity the "never-scanned
directories" resolution (bottom of this doc) called out for
`summarize_directories`.

## Prerequisite: `product_id` — done

`Entry` (`model/Entry.py:38`) now has `product_id: uuid.UUID | None`, a
foreign key to the new `Product` table (`model/Product.py`), added via
migration `454ae90a7155_add_product_id_fk_to_entry.py`. `Entry` also already
exposes a `has_product` property (`model/Entry.py:72`,
`self.product_id is not None`) — the exact field tool 1 needs per-file.
Prerequisite for tools 1–2 is resolved.

## Architecture pattern: skip `CommandProtocol`, follow `status.py` instead

`CommandProtocol` (`process(starting_path, process_recursively, force, ctx)
-> ResultType`) was shaped for `UpdateCatalogCommand` — a long-running write
operation with progress reporting. These three tools are fast, synchronous,
read-only queries with no `force` concept and nothing to report progress on.
Forcing them through that Protocol would mean unused parameters on every
call. Better fit: the existing `mcp/status.py` pattern — a plain
`register(mcp, catalog)` function with the query logic inline or in a small
helper, no Command class, no `ctx` needed since there's nothing to report.

## Tool 1 — `list_directory_entries(path, recursive=False)`

**Status: complete.** See implementation notes above.

Lists files directly in `path` (or its subtree if `recursive=True`), each
flagged with product-identification status.

```python
def list_directory_entries(path: Path, recursive: bool = False) -> dict[str, object]:
    """Files in `path`, each showing whether a product has been identified."""
```

Response shape:
```json
{
  "path": "books/Systems/Call of Cthulhu",
  "files": [
    {"filename": "Keeper Rulebook.pdf", "path": "books/Systems/Call of Cthulhu/Keeper Rulebook.pdf", "media_type": "pdf", "cataloged": true, "has_product": true},
    {"filename": "scan_042.pdf", "path": "books/Systems/Call of Cthulhu/scan_042.pdf", "media_type": "pdf", "cataloged": true, "has_product": false},
    {"filename": "never_scanned.pdf", "path": "books/Systems/Call of Cthulhu/never_scanned.pdf", "media_type": null, "cataloged": false, "has_product": false}
  ],
  "count": 2,
  "with_product": 1,
  "without_product": 1
}
```

- `path` (library-relative, added post-launch — bug found via the
  `rpg-librarian-mcp-test` skill): a recursive listing spans multiple
  subdirectories, so two same-named files in different folders (e.g. two
  scans both called `book.txt`) were otherwise indistinguishable in the
  response — only `filename` (the bare name) was returned. `filename` is
  kept alongside it rather than removed, since non-recursive callers that
  just want the bare name still have it without re-deriving it from `path`.
- `has_product` (bool) rather than exposing `product_id` itself — the LLM
  needs "is this done," not the UUID; matches the earlier decision to never
  surface raw DB identity to the caller.
- Query: `select(Entry).where(Entry.parent_path == path)` (non-recursive) or
  filtered in Python via `is_relative_to` (recursive) — same precedent as
  the deletion-reconciliation fix from the previous session (SQL `LIKE` on
  `parent_path` is unreliable due to `ParentPathType`'s trailing-slash
  normalization; Python-side `pathlib` filtering is the established,
  verified-correct approach here).
- `recursive=True` has no result cap in this draft — worth a
  `limit`/truncation flag (mirroring `UpdateCatalogResult`'s `max_errors`
  capping pattern) if this ever gets called on a directory with thousands of
  files. Flagging, not resolving, since actual limits depend on real usage
  patterns not yet observed.

## Tool 2 — `summarize_directories(path, include_complete=False, limit=100)`

**Status: complete.** See implementation notes above. `limit` was added by
the "Resolved" section at the bottom of this doc (cap-and-flag, no
pagination) and is reflected in the signature and response shape here.

The "what's left to do" overview: one row per directory under `path`, counts
only — not per-file detail (that's tool 1's job for a specific directory
once the LLM has picked one).

```python
def summarize_directories(
    path: Path, include_complete: bool = False, limit: int = 100
) -> dict[str, object]:
    """Per-directory product-identification counts, recursively under `path`."""
```

Response shape:
```json
{
  "path": "books",
  "directories": [
    {"path": "books/Systems/Shadowrun", "scanned": true, "with_product": 4, "without_product": 19},
    {"path": "books/Generic/Adventures", "scanned": true, "with_product": 12, "without_product": 0},
    {"path": "books/Systems/Unscanned", "scanned": false, "with_product": 0, "without_product": 0}
  ],
  "total_directories": 3,
  "truncated": false
}
```

- **Sorted by `without_product` descending by default** — directly serves
  "identify what still needs to be done, pick a next step": the top row is
  where the most unfinished work is concentrated.
- `include_complete=False` by default drops any directory with
  `without_product == 0` — keeps the response focused on remaining work
  rather than dumping all ~14,200 directories in the library every time.
- **Query design, two-phase to avoid both known pitfalls:**
  1. SQL-side `GROUP BY parent_path` with conditional counts (`sum(case when
     product_id is not null then 1 else 0 end)`) — pushes aggregation into
     SQLite, so this is one query returning ~14k rows (one per distinct
     directory), not 76k (one per file).
  2. Python-side `is_relative_to(path)` filter on those grouped results —
     same reasoning as tool 1, avoids the `LIKE`-prefix bug, and is cheap
     now because it's filtering thousands of grouped rows, not the full
     entry table.
- This is a meaningfully different approach from the full-table-scan-in-Python
  pattern used for deletion reconciliation — that one needed the *set of
  files on disk* for comparison and couldn't be aggregated in SQL; this one
  is a pure aggregation query, so pushing the `GROUP BY` to SQL is both
  correct and cheap, worth doing even though the prior precedent used a full
  scan.

## Tool 3 — `list_errors(path=None, stage=None)`

**Status: complete.** Implemented in `mcp/errors.py`. `occurred_at` is
serialized with `.isoformat()` explicitly — `Error.occurred_at` (unlike
`Entry`'s timestamps) has no `sa_type=UTCDateTime`, so it comes back naive
rather than UTC-aware; explicit serialization sidesteps relying on that
distinction leaking into the response.

```python
def list_errors(path: Path | None = None, stage: ErrorStage | None = None) -> dict[str, object]:
    """All recorded errors, optionally scoped to a directory subtree or a stage."""
```

Response shape:
```json
{
  "errors": [
    {"path": "stl/Loot/broken.stl", "stage": "populate_file_data", "error_text": "...", "occurred_at": "2026-07-20T..."}
  ],
  "count": 1
}
```

- Requires a join `Error.entry_id == Entry.id` to surface `path` instead of
  the raw `entry_id` UUID — same no-raw-DB-identity rule as everywhere else
  in this project.
- `stage` filter exists mainly for forward-compatibility: today `ErrorStage`
  only has `populate_file_data`, but `work_remaining.md` already flags
  future stages (ISBN lookup, OCR) that this filter will matter for once
  they exist.
- `path` filter uses the same recursive/`is_relative_to` approach as tools
  1–2 for consistency.

## Escape-hatch tools: `run_readonly_query` and `get_catalog_schema`

**Status: complete** for both tools below. Implemented in
`mcp/readonly_query.py`, using `readonly_connection` in `db.py` exactly as
specced (`catalog.db_path.as_uri() + "?mode=ro"` rather than manual
`f"file:{...}"` string-building, so library-root paths containing spaces or
`?`/`#` don't break the URI).

Goal: let the LLM run ad-hoc queries against `.catalog/catalog.db` for
anything not covered by a purpose-built tool above, without any risk of
mutating the catalog. Read-only-ness is enforced two ways at once (belt and
suspenders): the connection itself is opened read-only at the SQLite level,
*and* the query text is checked before it ever reaches the connection.

### Connection: `readonly_connection(catalog)` in `db.py`

A new context manager alongside `session_scope`, using the stdlib `sqlite3`
module directly rather than SQLAlchemy — these tools return raw SQL results
(arbitrary columns) and raw DDL text, not ORM models, so the ORM layer adds
nothing here.

```python
@contextmanager
def readonly_connection(catalog: Catalog) -> Generator[sqlite3.Connection]:
    """A connection to the catalog db that SQLite itself refuses to write through."""
    ensure_bootstrapped(catalog)  # a plain read-write op, done before opening read-only
    conn = sqlite3.connect(f"file:{catalog.db_path}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()
```

- `mode=ro` is the real guarantee — SQLite raises on any write attempt
  through this connection, full stop, regardless of what SQL text reaches
  it.
- `ensure_bootstrapped` runs first (via the normal read-write path) so a
  brand-new catalog works from either tool without requiring
  `update_catalog` to have run first.

### Tool 4 — `run_readonly_query(sql, limit=500)`

```python
def run_readonly_query(sql: str, limit: int = 500) -> dict[str, object]:
    """Run one read-only SQL statement against the catalog db and return the result."""
```

- **Statement-shape check (whitelist, not blacklist):** reject unless the
  trimmed, case-insensitive SQL starts with `SELECT` or `WITH`. A whitelist
  avoids having to enumerate every dangerous keyword (`ATTACH`, `PRAGMA`,
  `DROP`, ...) — anything not starting with `SELECT`/`WITH` is rejected
  regardless of what it is.
- **Single statement only:** reject if a bare `;` appears before the end of
  the string (outside string literals). `sqlite3`'s `execute()` (as opposed
  to `executescript()`) would otherwise silently ignore everything after
  the first `;`, which is a worse failure mode than a loud rejection.
- **Row cap:** `limit` is clamped to a hard max of 500 (default 500, the
  LLM may ask for fewer). Internally fetch `min(limit, 500) + 1` rows via
  `fetchmany()`; return only the requested count and set `"truncated":
  true` if the extra row was present. No exact total-row count is computed
  — that would require re-running the query wrapped in `SELECT COUNT(*)
  FROM (...)`, roughly doubling cost for arbitrary/expensive queries, for a
  number the LLM won't act on differently than the boolean already tells it
  to.
- **Result shape** breaks from the list-of-dicts convention used by tools
  1–3, deliberately — columns are named once instead of repeated per row,
  which matters here because this tool is the one place result sets can
  legitimately get wide and long:
  ```json
  {
    "columns": ["parent_path", "filename", "media_type"],
    "rows": [
      ["books/Systems/Shadowrun", "Core Rulebook 6E.pdf", "pdf"],
      ["books/Systems/Shadowrun", "scan_019.pdf", "pdf"]
    ],
    "truncated": false
  }
  ```
- **Errors propagate**, not caught into a structured `{"error": ...}`
  field. A bad query is a single all-or-nothing failure (unlike
  `update_catalog`, which needs structured per-file errors because
  individual files can fail independently within one call) — letting
  FastMCP's normal tool-error path handle it avoids a second, redundant
  error convention.

### Tool 5 — `get_catalog_schema()`

```python
def get_catalog_schema() -> dict[str, object]:
    """The full schema (CREATE TABLE DDL) of every domain table in the catalog db."""
    with readonly_connection(catalog) as conn:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        ).fetchall()
    return {"tables": [{"name": name, "sql": sql} for name, sql in rows]}
```

Response shape:
```json
{
  "tables": [
    {"name": "Entry", "sql": "CREATE TABLE \"Entry\" (\n\tid CHAR(32) NOT NULL, ...)"},
    {"name": "Error", "sql": "CREATE TABLE \"Error\" (\n\tid CHAR(32) NOT NULL, ...)"}
  ]
}
```

- Returns raw `CREATE TABLE` DDL rather than a hand-rolled JSON schema
  summary — the DDL already encodes columns, types, primary keys, foreign
  keys, and constraints in one string, at the same query cost as fetching
  just names/types, so there's no reason to build and maintain a summary
  format that would carry strictly less information.
- Filters out `sqlite_%` internal bookkeeping tables and `alembic_version`
  (migration plumbing, a single meaningless row) — neither is ever a
  legitimate query target, so both are pure noise in every response.
- Takes no parameters; there's exactly one schema, for the one catalog db
  this server operates on.

## Tool 6 — `move(source, destination)`

**Status: complete.** Implemented in `mcp/move.py`. One addition beyond the
original design: `destination` depth is validated *before* any disk or DB
change (same "reject early" principle the design already applies to
existing-destination and missing-source checks). This is required by the
same `ParentPathType` depth-&lt;2 bind rejection noted above — a folder
moved to a top-level destination, or a file moved to a depth-&lt;2
destination, can never be represented as a valid `Entry.parent_path`.
Without this check the rejection would otherwise surface at
`session.commit()`, *after* step 4's disk rename had already succeeded,
inverting the spec's "unreliable step happens last" ordering guarantee.

Moves a file or folder from one location to another, both places inside the
library root. Both the filesystem and the catalog are updated so they never
disagree about where something lives.

```python
def move(source: Path, destination: Path) -> dict[str, object]:
    """Move a file or folder to a new location within the library, updating the catalog to match."""
```

Response shape:
```json
{
  "source": "books/Systems/Shadowrun/misc",
  "destination": "books/Systems/Shadowrun/Adventures/misc",
  "kind": "folder",
  "entries_updated": 14
}
```

`entries_updated` is `0` or `1` for a single-file move, or the count of
`Entry` rows rewritten for a folder move. It does not count uncataloged
files that rode along on disk as part of a folder move (see below) — those
have no `Entry` row to update.

### One tool, not `move_file`/`move_folder`

A single tool dispatches on whether `source` is a file or a directory, same
precedent as `update_catalog`'s `path` param handling both cases. A
single-file move is the degenerate case of a folder move's catalog update:
one `Entry` row rewritten by exact match, instead of many rewritten by
prefix match.

### `destination` is always an explicit full path — no `mv`-style inference

Unlike Unix `mv`, `destination` is never treated as "a directory to drop
`source` into by its existing name." It is always the literal path the item
ends up at, filename/dirname included. This also means `move` does rename
and relocate in one call — the destination filename does not need to match
the source filename.

Rejected: `mv`-style dual-mode inference (if `destination` exists and is a
directory, move into it; otherwise treat it as the new full path). Rejected
because that mode-switch is a classic source of surprising behavior
(trailing-slash mistakes, "did it go into the folder or replace it") — an
unambiguous contract is safer for an LLM caller, which can already compute
`dest_dir / source.name` itself for "into" semantics.

### Never overwrite; no folder merge

If `destination` already exists on disk — file or folder — the call fails.
No `overwrite` flag, no directory-merge mode. This is a deliberate,
uniform rule (one check, same for files and folders) rather than two
different collision policies:

- **Files**: overwriting would silently destroy catalog history (hash,
  timestamps, future product linkage) for the replaced entry.
- **Folders**: merging reintroduces per-child collision ambiguity (partial
  success — "3 children moved in, 2 errored, here's why") that the rest of
  this design deliberately avoids. If the caller wants to consolidate one
  folder's contents into an existing folder, that's an explicit per-child
  loop of unambiguous single moves, not a merge mode here.

`source == destination` is automatically rejected by this same rule, since
the destination trivially "already exists."

**Implementation note:** the disk-existence check turned out not to be the
whole story. A stale `Entry` row can exist at a path with no file on disk
(disk/catalog drift — the condition `update_catalog`'s deletion
reconciliation exists to repair). Writing over that row would violate
`Entry`'s `UniqueConstraint("parent_path", "filename")` at commit time,
which is *after* the rename in the ordering below — so this is checked
up front too, alongside the disk-existence and depth checks, not left to
surface at commit.

### Ordering: DB update before disk move, disk move before commit

Disk operations and SQLite commits cannot share one atomic transaction, so
ordering is chosen to make the *unreliable* step (the disk move) happen
last, after the *reliable* step (a DB transaction that can always be rolled
back) is provably reversible:

1. Open `session_scope`, resolve `source`/`destination` to relative paths
   via `Catalog.to_relative` (this is what enforces the "cannot move outside
   the library root" rule — same mechanism `UpdateCatalogCommand` already
   relies on, no new boundary check needed).
2. Rewrite the catalog in-memory: for a file, update the one matching
   `Entry`'s `parent_path`/`filename`; for a folder, update every `Entry`
   where `entry.parent_path.is_relative_to(source_relative)`, replacing the
   `source_relative` prefix with `destination_relative` (Python-side
   `is_relative_to` filtering, not SQL `LIKE` — same
   trailing-slash-normalization reasoning as tools 1–2 above). Rows are
   `session.add`ed but not yet committed.
3. `destination.parent.mkdir(parents=True, exist_ok=True)` — missing
   intermediate destination directories are created automatically. Common
   during reorganization (inventing a new category folder), low-risk
   (an empty directory is trivially reversible), so no separate
   "create folder" step is required first.
4. `source_absolute.rename(destination_absolute)` — a same-filesystem
   rename is used (not `shutil.move`), valid because both paths are already
   proven to be inside the same library root.
5. If step 4 raises, let the exception propagate — `session_scope`'s
   existing `except Exception: session.rollback(); raise` means the
   uncommitted DB rewrite from step 2 is discarded automatically, and
   nothing is committed.
6. If step 4 succeeds, `session.commit()`.

### Works on uncataloged sources

`source` does not need an existing `Entry` (or, for a folder, does not need
every file inside it to have one) — the disk move happens regardless.
Uncataloged files simply have no row to rewrite in step 2; they move on
disk for free as part of the folder rename in step 4. Requiring prior
`update_catalog` first would make `move` depend on cataloging for no real
reason — mirrors how `update_catalog` itself treats "file exists, no row
yet" as the normal case, not an error.

### Single item per call, no batching

One `(source, destination)` pair per call, not a list of pairs. Batching
would reintroduce the same partial-success ambiguity rejected for folder
merges (Q4-equivalent) — "N succeeded, M failed, here's why" — for an
operation designed to be an unambiguous, reviewable, all-or-nothing unit.
The caller loops over calls itself when moving several things; each call
staying atomic means an interrupted loop is safe to resume.

### Architecture pattern: lightweight `register()`, not `CommandProtocol`

Despite being a write operation, `move` is structurally one `Path.rename()`
call plus one bulk in-memory rewrite committed in one transaction — nothing
comparable to `update_catalog`'s per-file iteration, and nothing meaningful
to report progress on even for a folder with thousands of entries
underneath. Same reasoning `tools_spec.md` already used to route the
read-only tools (1–3 above) away from `CommandProtocol`: that Protocol's
shape was fit specifically to `UpdateCatalogCommand`, and forcing an
unrelated tool through it for consistency alone just produces unused
`process_recursively`/`force`/`ctx` parameters. Follows the `status.py`
pattern instead: plain `register(mcp, catalog)`, small helper for the
DB-rewrite logic, no `Context`.

### Errors propagate

Out-of-root paths (`Catalog.to_relative` raising `ValueError`),
destination-already-exists, and source-does-not-exist all propagate as
raised exceptions rather than a structured `{"error": ...}` return — same
convention as `run_readonly_query`'s "a bad query is a single all-or-nothing
failure" reasoning. `move` is likewise all-or-nothing: there is no
per-child partial-failure case left to report structurally once folder
merge is rejected.

## Tool 7 — `read_pdfs(path, process_recursively=False, force=False)`

**Status: complete.** Implemented per the design in
`.planning/read_pdf_spec.md`, reached via brainstorm on 2026-07-30.
`mcp/read_pdfs.py`, `commands/ReadPdfsCommand.py`, `tools/barcode.py`,
`tools/text_extraction.py`, `tools/ocr.py`, `tools/pdf_rendering.py`,
`llm/settings.py`, `llm/pdf_judgment.py`, model `PdfContents`, migration
`592aeb22d8d0`.

One addition beyond the original design: `UpdateBaseCommand` gained a
`fatal_exceptions: ClassVar[tuple[type[BaseException], ...]]` hook (default
`()`, no behavior change for existing subclasses) so `ReadPdfsCommand` can
mark `litellm.AuthenticationError`/`RateLimitError` as run-aborting instead
of per-entry -- the base class's per-entry try/except had no prior concept
of a exception that should propagate rather than being recorded as an
`Error` row.

```python
async def read_pdfs(
    path: Path,
    ctx: Context,
    process_recursively: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Extract barcode/ISBN/ISSN/sample-text/LLM-derived signal from PDFs."""
```

Same signature shape and response shape (`UpdateResult._asdict()` plus
`errors`) as `update_metadata`, built on `UpdateBaseCommand` via a new
`ReadPdfsCommand`. Unlike `update_metadata`, this tool is PDF-only —
non-PDF entries are silently `skipped`, not errored.

Produces a new raw, per-source table `PdfContents` (0..1 on `Entry`,
`entry_id`-keyed, upserted in place — same shape as `PdfMetadata`), and
**removes** the `barcode`/`isbn`/`issn`/`sampled_text` columns from
`PdfMetadata`, which were unpopulated placeholders for this exact feature.

See `read_pdf_spec.md` for the full design: page-sampling/dedup, barcode →
ISBN/ISSN resolution order, OCR via `pytesseract`, LLM-derived
`description`/`possible_system` via `litellm` with structured output, error
classification (per-entry vs. hard-fail), and the checked-in LLM settings
file.

## Tools 8–9 — `search_rpg_geek`, `lookup_rpg_geek_product`, `search_dtrpg`

**Status: complete.** Design reached via brainstorm on 2026-07-30,
implemented the same day. See `.planning/rpg_lookup_spec.md` for the full
design: vendored RPGGeek/DriveThruRPG clients (`rpggeek/client.py`,
`dtrpg/client.py`, adapted from the sibling `rpggeek-mcp`/`dtrpg_mcp`
projects), normalized `ProductCandidate`/`ProductLookupDetails` response
shapes (`commands/ProductLookupResult.py`), lazy client construction
(`mcp/rpg_geek.py`, `mcp/dtrpg.py`, `@lru_cache` factories) so a missing
API key doesn't crash server startup, and the decision to drop a separate
`lookup_dtrpg_product` tool (DriveThruRPG's single-item endpoint 403s
regardless of auth; `search_dtrpg` already returns full details per hit).

```python
async def search_rpg_geek(
    name: str | None = None, isbn: str | None = None, max_values: int = 5
) -> list[ProductCandidate]:
    """Search RPGGeek for candidate products by name and/or ISBN."""

async def lookup_rpg_geek_product(rpggeek_id: int) -> ProductLookupDetails:
    """Fetch full product details for an RPGGeek item by its numeric id."""

def search_dtrpg(
    query: str, scope: Literal["library", "catalog"] = "catalog", max_values: int = 10
) -> list[ProductLookupDetails]:
    """Search DriveThruRPG (the caller's library, or the whole catalog) for
    products matching `query`, returning full details."""
```

Read-only for this batch — none of these three write to `Product`. A
future `identify_product`-style write tool is explicitly deferred; see
"Open items" in `rpg_lookup_spec.md`.

## Tool 10 — `lookup_isbn(isbn)`

**Status: complete.** Design reached via brainstorm on 2026-07-30,
implemented the same day. See `.planning/isbn_lookup_spec.md` for the full
design: vendors `~/proj/rpg-librarian`'s Google Books → Open Library →
Wikidata fallback chain into `isbn/lookup.py`, reuses `isbn/isbn.py`'s
existing validation instead of `isbnlib`'s own (`commands/
LookupIsbnCommand.py` validates/normalizes first, short-circuiting to
`None` with zero network calls for anything invalid -- including any
ISSN), and returns the same normalized `ProductLookupDetails` shape as the
RPGGeek/DTRPG tools (`source="isbn"`).

```python
def lookup_isbn(isbn: str) -> ProductLookupDetails | None:
    """Look up bibliographic metadata for an ISBN (Google Books, falling
    back to Open Library, then Wikidata). Returns None if `isbn` is
    invalid or no provider has data for it -- not an error. Does not
    support ISSN (periodical) lookups; an ISSN input reliably returns
    None."""
```

Real lookup failures (network/HTTP errors from every provider, or Google
Books itself being unusable -- quota/key/rate-limit) propagate as raised
exceptions rather than returning `None`, so the LLM can tell "no data
exists for this ISBN" apart from "the lookup couldn't be attempted."
New optional env var `GOOGLE_BOOKS_API_KEY` (documented in `.env.example`
and README once implemented).

## Resolved: never-scanned directories and result caps

1. **Never-scanned directories are surfaced, with zero counts.** A directory
   that exists on disk but has zero `Entry` rows must not look identical to
   a directory that is fully cataloged — `without_product == 0` cannot mean
   the same thing in both cases. Each directory row therefore carries an
   explicit `scanned: bool` in addition to `with_product`/`without_product`,
   and the default `include_complete=False` filter becomes "drop iff
   `scanned and without_product == 0`" (a never-scanned directory has
   `scanned=False`, `with_product=0`, `without_product=0`, and is kept).

   This is a real change to the query shape, not just the filter: the SQL
   `GROUP BY parent_path` aggregation only ever sees directories that
   already have at least one `Entry` row, so a never-scanned directory
   can't appear in that result set at all. Surfacing it requires walking
   the filesystem under `path` (e.g. `Path.iterdir`/`rglob` for real
   subdirectories) and set-diffing that against the directories the SQL
   grouping found — same shape as the full-scan used for deletion
   reconciliation, now applied to directories instead of files. This
   applies to both `list_directory_entries` (a directory with files but no
   `Entry` rows at all) and `summarize_directories`.

2. **Result cap via `limit` + `truncated`, no pagination.** No
   offset/cursor pagination — it doesn't fit the tool's actual use ("find
   the top of the work queue, act, ask again"; the LLM never needs page 2
   of a stale list, it just calls again after making progress). Instead,
   reuse the cap-and-flag convention already established elsewhere in this
   spec (`max_errors` on `update_catalog`, `truncated` on
   `run_readonly_query`): `summarize_directories` gets a `limit` param
   (default ~100, hard max ~1000), keeps its existing sort-by-
   `without_product`-descending, returns only the top `limit` rows, and
   sets `truncated: true` if more rows existed beyond the cap.

## Tool 11 — `update_product(path, title, identification_method, ...)`

**Status: complete.** Design reached via brainstorm on 2026-07-30,
implemented the same day. See `.planning/update_product_spec.md` for the
full design and implementation notes. This is the
`identify_product`-style write tool `rpg_lookup_spec.md`'s "Open items"
explicitly deferred: find-or-create a `Product` from caller-supplied
details, then link every entry under `path` to it.

```python
async def update_product(
    path: Path,
    title: str,
    identification_method: IdentificationMethod,
    ctx: Context,
    process_recursively: bool = False,
    description: str | None = None,
    artists: str | None = None,
    publisher: str | None = None,
    year: str | None = None,
    system: str | None = None,
) -> dict[str, object]:
    """Find or create a Product matching the given details, then link
    every entry under `path` to it."""
```

No `force` param — every entry under `path` whose `product_id` doesn't
already match the resolved product gets overwritten unconditionally, so
there's no "stale result" concept to bypass. Response shape adds
`product_id` and `created` (bool) to the usual scan-stats shape:

```json
{
  "scanned": 3, "skipped": 1, "succeeded": 2, "errored": 0, "errors": [],
  "product_id": "…", "created": true
}
```

## Tool 12 — `ingest_external_source(source_path, name)`

**Status: complete.** Design reached via brainstorm on 2026-07-30,
implemented the same day. Full design/rationale in `.planning/ingestion.md`.
Implemented in `mcp/ingest_external_source.py` — a plain
`register()`/business-logic-function pair (same architecture as `move`, not
`UpdateBaseCommand`), since this is one filesystem walk plus a report write,
nothing entry-scoped to iterate.

One addition beyond the original design: `source_path` is rejected outright
if it resolves *inside* the library root (`catalog.to_relative` succeeding
is the signal) — content already in the library isn't this tool's job,
`update_catalog` handles it directly, and allowing an in-root source risked
`_inbox/<name>/` nesting inside its own source tree on a careless call.

Copies only the new content from a path outside the library into
`_inbox/<name>/`, deduping by exact `sha256` against both the library and
any content already staged there from a prior run of the same source. The
one new capability the "friend hands you a pile of overlapping content"
scenario needs — everything after this (`update_catalog`, `read_pdfs`,
`update_product`, `classify_content_role`, `move`) is the existing
pipeline, unchanged, pointed at `_inbox/<name>/`.

```python
def ingest_external_source(source_path: Path, name: str) -> dict[str, object]:
    """Copy new (non-duplicate) content from an external path into
    `_inbox/<name>/`, deduping by content hash against both the library
    and any previously staged content under the same name."""
```

`source_path` is the one deliberate exception to "every tool path is
library-relative" — an absolute path outside the library root, since this
content isn't catalogable until after this call. Full per-file manifest
goes to a written report (`_inbox/<name>/_ingest_report.md`), not the tool
response — see `ingestion.md` for the report shape and why.

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

**Known, deliberately unhandled edge cases** (flagging, not resolving —
low-frequency enough that hand-fixing them beats adding scope):
- A second run against the same `name` **overwrites**
  `_ingest_report.md`, not appends — run 1's manifest is lost if a run 2
  happens before the first drop was triaged out of `_inbox/<name>/`.
- The report file itself lives inside `_inbox/<name>/`, so once
  `update_catalog` runs on the staging dir it becomes a cataloged `Entry`
  like anything else there (harmless, but worth knowing before wondering
  why a `.md` file shows up in `list_directory_entries`).

## Prerequisite: `Product.content_role`

**Status: complete.** New nullable, indexed enum column on `Product`
(`ContentRole`: `core_rules`, `adventures_and_scenarios`,
`settings_and_supplements`, `gm_and_player_aids`, `extras`), migration
`06f71334c29a` (`592aeb22d8d0` -> `06f71334c29a`). Null for agnostic
products — no role tier in the target scheme for them. New
`ProcessingStage.classify_content_role` value added alongside it. See
`ingestion.md` for the full field/enum definition.

## Tool 13 — `classify_content_role(path, process_recursively=False, force=False)`

**Status: complete.** Design reached via brainstorm on 2026-07-30,
implemented the same day. Full design/rationale in `.planning/ingestion.md`.
Implemented in `mcp/classify_content_role.py` /
`commands/ClassifyContentRoleCommand.py`, LLM judgment in
`llm/content_role_judgment.py` (`resources/prompts/content_role_prompt.jinja`),
same `litellm`-structured-output shape as `read_pdfs`'s `judge_pdf_contents`.

`UpdateBaseCommand`-shaped, same family as `read_pdfs`/`update_product`.
For each entry under `path`, classifies its product's `content_role` via an
LLM judgment over `Product.description` and any linked PDFs'
`PdfContents.sample_text`/`description` — no independent text extraction,
reuses `read_pdfs`'s output.

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

- `in_scope`: false for agnostic products (role doesn't apply). Resolved as
  a set of agnostic `Product.id`s once per `process()` call, not queried
  per entry inside `in_scope` — `in_scope` takes no `session` and, per
  `UpdateBaseCommand`'s own contract, must apply even when `force=True`
  (system-agnostic content has no role tier to classify, full stop, not a
  staleness condition `force` should be able to bypass). One addition
  beyond the original design: `process()` is overridden (same pattern as
  `ReadPdfsCommand`'s Tesseract check) to resolve that set before
  delegating to the base loop.
- `should_process`: true only if the product has no `content_role` yet or
  has a recorded error for this stage — classifies once per product, not
  once per entry, even though a product can span several entries. Also
  independently re-checks the agnostic condition (belt-and-suspenders with
  `in_scope`'s precomputed set, since `should_process` is called with a
  live `session` anyway).
- No usable text (`Product.description` and no linked
  `PdfContents.sample_text`) → skipped, not errored; re-run after
  `lookup_isbn`/`lookup_rpg_geek_product`/`read_pdfs` populates one.
- `_gather_context` concatenates a product's description plus every linked
  PDF entry's full `sample_text`/`description`, unbounded — flagging, not
  resolving: a product spanning many large PDFs (e.g. dozens of
  pre-generated character sheets) could exceed the model's context window
  and error on every entry under it, with no truncation/summarization
  fallback in this version.

Response shape: standard `UpdateResult._asdict()` plus `errors`, same as
`read_pdfs`.

## Tool 14 — `find_duplicates(path=None)`

**Status: complete.** Implemented in `mcp/find_duplicates.py`, no `Command`
class — same lightweight `register()` pattern as `list_errors`/
`list_directory_entries` (a fast, synchronous, read-only query with no
`force`/progress concept).

Entries whose `sha256` matches at least one other entry, grouped by hash.

```python
def find_duplicates(path: Path | None = None) -> dict[str, object]:
    """Entries whose sha256 content hash matches at least one other entry,
    grouped by hash."""
```

- `path`, if given, must be an absolute path **to a directory** and scopes
  the scan (recursive) to that subtree; a file path is rejected
  (`"... is a file, not a directory -- a duplicate-scan scope must be a
  directory"`) rather than silently returning an empty/wrong result —
  `entries_under`'s `is_relative_to` filtering has no meaningful
  interpretation for a single-file scope, unlike `list_errors`, which
  special-cases an exact-path match instead. A non-existent path raises,
  matching `list_errors`'s convention.
- With no `path`, every cataloged `Entry` is loaded (`select(Entry)`, not a
  scalar-column `select` — the established workaround for `ty`'s inability
  to resolve `sqlmodel`'s multi-column `select()` overloads, same as
  `ingest_external_source`'s `_library_hashes`) and grouped by `sha256` in
  Python. A full-table scan, not a SQL `GROUP BY ... HAVING count > 1` —
  consistent with every other aggregation in this spec
  (`summarize_directories`'s grouped counts, `move`'s catalog rewrite):
  Python-side grouping over an already-fetched result set, not pushed to
  SQL.
- Each group carries every entry's library-relative `path` and
  `has_product`, so an already-identified copy can be told apart from an
  unidentified one when deciding which to keep — same `has_product`-not-
  `product_id` convention as `list_directory_entries` (never surface raw
  DB identity).
- Groups are sorted by `count` descending, then `sha256` — most-duplicated
  content first, mirroring `summarize_directories`'s "biggest remaining
  work first" sort.
- **Exact-hash dedup only**, same scope boundary as `ingest_external_source`
  — near-duplicates (different scans/editions/printings of the same
  product) are not caught here; that's a `update_product`-time judgment
  call, not a hash comparison.

Response shape:
```json
{
  "duplicate_groups": [
    {
      "sha256": "3f9a...",
      "count": 2,
      "entries": [
        {"path": "DriveThruRPG/Chaosium/Petersen's Abominations/Abominations.pdf", "has_product": true},
        {"path": "_inbox/dave/Chaosium/Petersen's Abominations/Abominations.pdf", "has_product": false}
      ]
    }
  ],
  "duplicate_group_count": 1,
  "duplicate_file_count": 2
}
```

## Tool 15 — `remove(path, process_recursively=False, force=False)`

**Status: complete.** Implemented in `mcp/remove.py`, backed by
`commands/RemoveCommand.py` (`UpdateBaseCommand` subclass — reuses its
entry-resolution/per-entry error handling/progress reporting, same family
as `read_pdfs`/`update_product`/`classify_content_role`).

Moves every cataloged entry under `path` (or `path` itself, for a single
file) into `.catalog/trash/`, mirroring its library-relative path there
(intermediate directories created as needed), and removes its `Entry` row.
Not a delete — the file is relocated on disk, not destroyed.

```python
async def remove(
    path: Path,
    ctx: Context,
    process_recursively: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Move every cataloged entry under `path` into `.catalog/trash/`,
    removing it from the catalog."""
```

- **`should_process` is unconditionally `True`.** Removal has no staleness
  concept the way enrichment commands (`read_pdfs`, `classify_content_role`)
  do — an already-removed entry has no `Entry` row left to be resolved
  again on a later run, so there's nothing to skip. `force` is present only
  for interface consistency with sibling `UpdateBaseCommand` tools; it has
  no observable effect here.
- **Ordering, same "unreliable step last" principle as `move`:**
  `process_one` calls `session.delete(entry)` (queued, not yet committed)
  *before* the disk rename. If the rename raises,
  `UpdateBaseCommand`'s per-entry rollback discards the queued delete
  automatically — the file and its `Entry` row are left untouched rather
  than ending up removed-from-catalog but still on disk at the old path.
- **Never overwrites the trash** — if the mirrored destination under
  `.catalog/trash/` already exists (e.g. removing, restoring by hand, then
  removing the same path again), that entry errors (recorded as a
  per-entry `Error`, same as any other `UpdateBaseCommand` failure) rather
  than silently overwriting the earlier trashed copy. Same "never overwrite,
  no merge" rule `move` already applies to its own destination collisions.
- **No new stage-specific validation for missing files/stale rows** —
  `Path.rename` raising `FileNotFoundError` for an already-drifted Entry
  (file deleted outside the tool) propagates as a normal per-entry error,
  same as any other filesystem failure in this family of commands.
- `.catalog/` itself is already excluded from every filesystem walk
  (`tools/path_helper.py`'s dot-prefix filter), so trashed content never
  gets re-discovered and re-cataloged by a later `update_catalog` run.
- **Path-traversal guard in `process_one`.** `entry.path`'s components are
  normally validated (never absolute, no `..`) by `ParentPathType` on every
  bind — but a row planted by raw SQL (`conftest.insert_raw_entry`, the
  `poisoned_catalog` fixture; commit f4d6fc6 fixed real bugs from exactly
  this class of row) bypasses that. `process_one` resolves the computed
  trash path and rejects the entry (a per-entry error, not a crash) unless
  it's actually inside `.catalog/trash/` — found via review, not a report,
  since nothing upstream guarantees every `Entry` row is well-formed.
- **Empty-directory pruning, added post-implementation.** `process()` is
  overridden (same shape as `ReadPdfsCommand`'s Tesseract check /
  `ClassifyContentRoleCommand`'s agnostic-set precompute) to prune
  directories left empty by the run after the base loop completes —
  without it, "removes all files under the passed in path" left the empty
  directory shells behind, which `summarize_directories` would then surface
  as permanent phantom `scanned: false` rows. Two constraints on the
  pruning, both load-bearing:
  - **Scoped to directories this run actually removed a file from**
    (tracked per-entry in `process_one` via `_directories_touched`), not a
    fresh filesystem scan for anything empty — an incidentally-empty
    sibling folder the run never touched is not this call's business.
  - **Never prunes above the requested `starting_path`.** Cascades upward
    while a parent also ends up empty, but stops at `starting_path` itself
    rather than continuing into its ancestors — "remove everything under
    this path" scopes the cleanup to that path, not license to also sweep
    out directories above it. A single-file `starting_path` has no
    directory scope to prune at all.
  - Processing order is deepest-candidate-first (`max(..., key=len(parts))`
    each iteration, not a plain stack) — a directory and its own
    subdirectory can both be touched in the same run, and a failed `rmdir`
    (non-empty) is never retried, so the parent must never be attempted
    before its child is resolved.

Response shape: standard `UpdateResult._asdict()` plus `errors`, same as
`read_pdfs`/`classify_content_role`.
