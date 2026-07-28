# MCP tools — spec

Durable spec for all MCP tools in this project. Goal: give the LLM a way to
update the catalog, check the status of cataloging work, identify what
still needs to be done, and pick a next step.

| Tool | Status |
| --- | --- |
| `update_catalog` | complete |
| `list_directory_entries` | unstarted |
| `summarize_directories` | unstarted |
| `list_errors` | unstarted |
| `run_readonly_query` | unstarted |
| `get_catalog_schema` | unstarted |
| `move` | unstarted |

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

**Status: unstarted** for all three tools below. Design only, not
implemented. Three tools: per-directory file listing, recursive
per-directory counts, and error listing.

## Prerequisite: `product_id` does not exist yet

`Entry` (`model/Entry.py`) currently has no product-identification field —
just `id`, `parent_path`, `filename`, `sha256`, `size_in_bytes`, `mime_type`,
`media_type`. Product identification is listed as not-started work in
`work_remaining.md` (no ISBN/enrichment tooling exists yet).

This design assumes `product_id: uuid.UUID | None` gets added to `Entry` as
a prerequisite schema change (its own migration, not part of this design).
Flagging this as a dependency, not resolving it here.

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

**Status: unstarted.**

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
    {"filename": "Keeper Rulebook.pdf", "media_type": "pdf", "has_product": true},
    {"filename": "scan_042.pdf", "media_type": "pdf", "has_product": false}
  ],
  "count": 2,
  "with_product": 1,
  "without_product": 1
}
```

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

## Tool 2 — `summarize_directories(path, include_complete=False)`

**Status: unstarted.**

The "what's left to do" overview: one row per directory under `path`, counts
only — not per-file detail (that's tool 1's job for a specific directory
once the LLM has picked one).

```python
def summarize_directories(path: Path, include_complete: bool = False) -> dict[str, object]:
    """Per-directory product-identification counts, recursively under `path`."""
```

Response shape:
```json
{
  "path": "books",
  "directories": [
    {"path": "books/Systems/Shadowrun", "with_product": 4, "without_product": 19},
    {"path": "books/Generic/Adventures", "with_product": 12, "without_product": 0}
  ],
  "total_directories": 2
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

**Status: unstarted.**

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

**Status: unstarted** for both tools below. Design only, not implemented.

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

**Status: unstarted.** Design only, not implemented.

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
