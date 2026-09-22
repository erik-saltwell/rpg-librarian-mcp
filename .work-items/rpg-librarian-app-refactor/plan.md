# Plan: implement the new rpg-librarian app

Phased implementation of [intent.md](intent.md) and [catalog-schema.md](catalog-schema.md).
Those two documents are the specification; this plan does not repeat their reasoning.
No rubric exists for this item by the user's decision (see `item.md`), so phases carry
verification steps but no numerical scoring.

## Standing constraints

- No new unit tests or test tooling (project verification policy). Verification is
  `uv sync`, `uv run ty check`, `uv run ruff check`, direct CLI execution against a
  scratch dump and library directory, and inspecting the SQLite catalog.
- v1's tests under `packages/rpg-librarian-mcp/tests/` leave with the v1 package in
  the final phase. That is package removal, not test deletion as a side effect; the
  tools package tests are untouched.
- The pre-commit hooks run `ruff`, `ty`, and `scripts/check_migrations.py`, which is
  hard-wired to v1's `alembic.ini`. Phase 1 must repoint it or hooks fail.

## Code inspected

Everything below was read during planning; paths are current as of commit `6a19dc7`.

**Reusable as-is (`packages/rpg-librarian-tools`, public API per its README):**
`files.inspect_file` (media type, MIME, SHA-256, size), `pdf.extract_text`,
`pdf.scan_identifiers`, `pdf.assess_images`, `identifiers.find_publication_identifiers`,
`dtrpg.search_products` / `search_library`, `rpggeek.search` / `get_product`,
`request_policy.RequestPolicy`, `errors.*`. Package-private `_isbn/` exists but is not
exported; the v1 ISBN lookup lives in `rpg_librarian_mcp/isbn/lookup.py` (Google Books
and Open Library) and must be ported or promoted.

**Port from v1 (`packages/rpg-librarian-mcp/src/rpg_librarian_mcp/`):**

| v1 location | What | Reuse |
|---|---|---|
| `infrastructure/isolated_worker.py` | `IsolatedWorkerPool` (pebble) and `SynchronousWorkerPool` for crash-isolated mesh/PDF work | Copy |
| `observability.py` | structlog wide-event logging: `CallTracker`, `EntryTracker`, `ToolCallLoggingMiddleware` | Copy; rename entry → file |
| `progress.py` | `ProgressReporter`, CLI and MCP implementations | Copy CLI side; MCP side only if a long tool remains |
| `metadata/extractors/*` | audio (mutagen), image (Pillow), mesh (trimesh), pdf, svg, video (pymediainfo) extractors and `generate_extractor` | Copy, retarget to new tables |
| `mcp/readonly_query.py` | read-only SQL guard (leading-word denylist, semicolon check, `LIMIT` cap 500) | Copy |
| `db.py` | alembic-upgrade-on-open, `readonly_connection` | Copy the pattern; new migration chain |
| `llm/pdf_judgment.py`, `llm/settings.py` | litellm call producing description / possible_system | Copy into `enrich` |
| `commands/UpdateCatalogCommand.py` | walk + mtime skip rule shape | Reference only; rewrite for roots and size+mtime |
| `cli.py` | argparse subcommand layout | Reference for style |
| `server.py` | FastMCP construction and middleware | Reference |
| `model/*Metadata.py` | per-media columns | Source of the column lists already in the schema doc |

**Not carried:** `ContentRole`, `IdentificationMethod`, `ProcessingStage`,
`PdfContents`, the `move` / `remove` / `ingest_external_source` / `classify_content_role`
tools, `resources/CLAUDE.md` and skill seeding in `db.py`, the alembic `versions/`.

**Root wiring:** `pyproject.toml` already has `apps/*` in the uv workspace and
`apps/rpg-librarian/{src,tests}` in ruff `src`. The ty root and pytest testpaths
entries are still to add (deferred because ty errors on a missing root).

## Decisions on the earlier unknowns

Agreed with the user:

1. **Catalog file location: settled.** `./catalog.db` in the current working
   directory, overridable with `--catalog PATH` on every verb and
   `RPG_LIBRARIAN_CATALOG` in the environment.
2. **Evidence table columns:** settled during Phase 3 from the tools result types
   (DriveThruRPG, RPGGeek), the v1 ISBN lookup result, and the Google result shape
   below, not guessed in advance.
3. **Extractor dependencies:** carry over whatever the ported extractors import; drop
   the rest. Known after Phase 2.
4. **Report field names:** decided at implementation time.

## Decision: Google search through Serper

Agreed with the user: the per-file Google search in `enrich` uses **Serper.dev**
(`POST https://google.serper.dev/search`, `X-API-KEY` header, JSON body with `q` and
`num`, hits under `organic` with title, link, and snippet). Reasons: the expected volume
is thousands of queries per dump, which rules out the Google Programmable Search free
tier (100 per day) and that API's uncertain availability to new customers; Serper
returns real Google results at roughly $1 or less per 1,000 queries. Brave Search was
the recommended alternative.

Accepted risk: Serper is a third-party service that fetches Google results without
Google's sanction, so it could change terms, pricing, or disappear. The client is one
small function behind one module, so replacing the provider touches nothing else.

No unknowns remain except confirming, before Phase 3, that the user's Serper API key
returns results in a manual request.

## Phase 0: app scaffold and tooling

- [x] Create `apps/rpg-librarian/pyproject.toml` (hatchling, `requires-python >=3.14`,
      `[project.scripts] rpg-librarian = "rpg_librarian.__main__:main"`,
      `rpg-librarian-tools = { workspace = true }`), `README.md`, and
      `src/rpg_librarian/{__init__,__main__}.py` with an argparse parser that has the
      five verbs as stubs plus `serve` for the MCP server.
- [x] Create `apps/rpg-librarian/tests/` with a `.gitkeep`-equivalent (a `conftest.py`
      is acceptable) so the pytest path exists; add no tests.
- [x] Add `./apps/rpg-librarian/src` and `./apps/rpg-librarian/tests` to
      `[tool.ty.environment] root` and `apps/rpg-librarian/tests` to pytest
      `testpaths` in the root `pyproject.toml`.
- [x] Add config loading: `.env` via python-dotenv (port `catalog.load_env`), catalog
      path resolution per unknown 1.

Depends on: nothing. Outcome: `uv run rpg-librarian --help` lists the verbs;
`uv run ty check` and `uv run ruff check` pass with the empty app included.

Verification: `uv sync`, `uv run rpg-librarian --help`, `uv run ty check`,
`uv run ruff check`, `uv lock --check`.

## Phase 1: catalog model, migrations, `init`, `add-source`

- [x] SQLModel tables exactly as `catalog-schema.md` lists them: `root`, `product_type`,
      `product_line`, `product_line_alias`, `product`, `file`, `file_metadata`,
      `pdf_metadata`, `image_metadata`, `audio_metadata`, `video_metadata`,
      `mesh_metadata`, `file_text`, `file_text_analysis`, `error`, `review_flag`, and
      one evidence table per enrichment source (DriveThruRPG, RPGGeek, ISBN,
      `google_search_result`; columns settled in Phase 3, so those tables and their
      migration land there). Constraints: unique `(root_id, relative_path)`,
      indexed non-unique `sha256`, unique `(product_type_id, name)` on lines, unique
      `(product_line_id, name)` on products, unique `(product_line_id, alias)`,
      `keep` requires `product_id` (enforced in the write path, and as a CHECK if
      SQLite allows it cleanly).
- [x] Fresh alembic environment under `src/rpg_librarian/alembic/` with one initial
      migration; port the upgrade-on-open pattern from v1 `db.py`.
- [x] Repoint `scripts/check_migrations.py` at the new `alembic.ini`.
- [x] Path function module: `target_path(file, product, line, type, kept_count)` and
      the name sanitizer (illegal SMB/Windows characters, trailing dots, length).
      Single-file rule counts only `disposition = keep` files of that product.
- [x] Seed type list as a code constant; `init` creates the catalog, inserts missing
      types idempotently, registers the single `library` root, and refuses a second.
- [x] Bundle the `process-batch` and `review-items` skills and have `init` seed them
      into `.claude/skills/`, `.codex/skills/`, and `.gemini/skills/` without replacing
      an existing local copy.
- [x] `add-source` inserts a `staging` root, refusing paths nested in or containing an
      existing root; no scan.

Depends on: Phase 0. Outcome: `init` and `add-source` produce a catalog whose schema
matches the design document.

Verification: `uv run rpg-librarian init --library <scratch>/library`, then
`add-source <scratch>/dump_A`; `sqlite3 catalog.db .schema` matches the table list;
re-running `init` is a no-op; nested `add-source` is rejected; `uv run python
scripts/check_migrations.py` passes; hooks pass on commit.

## Phase 2: `scan`

- [x] Walk one root (or all roots by default), skipping `.trash/` and v1's filtered
      names; record `relative_path`, `size_bytes`, whole-second `mtime`.
- [x] Skip rule per the schema doc: unchanged size+mtime → update `last_seen_at`,
      clear `missing_since`, done. Otherwise copy local → `inspect_file` → media
      extractor → PDF text sample (first 5 + last 2 pages, OCR only where no text
      layer) → barcode scan (first 2 + last page) → `find_publication_identifiers`
      over the sample → delete local copy. Replace metadata/text rows; if the hash
      changed, reset disposition to `unfiled` and clear `product_id` and
      `duplicate_of_id`.
- [x] Port the extractors and the worker pool; run mesh and PDF work through the
      isolated pool as v1 does.
- [x] Hash join after each file: match against a row with `missing_since` set → move
      (update path, clear `missing_since`, keep product and disposition); match
      against a present row → set `duplicate_of_id` and `disposition = duplicate`,
      library copy winning, earlier-scanned winning within staging.
- [x] Missing detection: rows under a reachable root whose path is absent get
      `missing_since`; an unreachable root is skipped with a warning and nothing
      marked.
- [x] `error` rows per `(file_id, stage)`, overwritten on retry; per-file wide-event
      logs via the ported observability module; rich progress on the CLI.
- [x] `--force` to bypass the skip rule for a root; `clear-metadata`-style reset is
      covered by `--force`, so no separate verb.

Depends on: Phase 1. Outcome: a scanned dump is fully described in the catalog, with
duplicates flagged and re-runs skipping unchanged files.

Verification: scan a scratch dump containing at least one PDF with a text layer, one
scanned PDF, one image, one audio file, one mesh, and a duplicate of a file placed in
the library root; check row counts and `duplicate_of_id`; re-run and confirm every
file is skipped; touch a file's mtime and confirm it is reprocessed; move a file by
hand, rescan, and confirm the row's path updated rather than a duplicate appearing;
check the local temp directory is empty afterwards.

## Phase 3: `enrich`

- [x] Settle the evidence tables from the tools result types and the v1 ISBN result
      and add the migration.
- [x] Google search evidence: a stateless `rpg_librarian_tools.google.search(query,
      api_key, num=5, policy)` client in the tools package, calling Serper (one
      request sequence, explicit credentials, immutable result objects, documented in
      that package's README) and returning title, URL, and snippet per hit from
      Serper's `organic` list.
- [x] `google_search_result` table, one row per file: `query`, `results` (JSON list of
      title/URL/snippet, top 5), `fetched_at`. A file with no hits still gets a row
      recording the query, so it is not re-queried.
- [x] Query construction, deterministic and recorded: prefer an identified ISBN, then
      the embedded title, then the filename stem with its parent folder name; strip
      extension and separators. No LLM in query building.
- [x] Credential `SERPER_API_KEY` from `.env`; a missing key skips the Google source
      with one warning instead of failing the run. Honour `RequestPolicy`, and on an
      out-of-credits or rate-limit response stop the source cleanly, recording an
      `error` row, so a re-run resumes where it left off.
- [x] DriveThruRPG, RPGGeek, and ISBN lookups keyed from `file_text` identifiers and
      filename/embedded title, one row per file per source, with query and fetch
      time recorded; honour `RequestPolicy` and record `error` rows on failure.
- [x] Text analysis (a model reads the stored sample) into `file_text_analysis` (`description`, `possible_system`) from
      the text sample, porting `pdf_judgment.py`; a file needs enrichment when it has
      `file_text` and no `file_text_analysis` row.
- [x] `--source` filter to run one source (`dtrpg`, `rpggeek`, `isbn`, `google`, `text_analysis`), `--limit` for bounded runs, and
      resumability by simply re-running.

Depends on: Phase 2. Outcome: candidate evidence exists for every scannable file
without any product being created.

Verification: run `enrich` on the scratch dump with credentials in `.env`; confirm
rows per source (including a `google_search_result` row whose `query` matches the
rule above and whose `results` parse as JSON), that a re-run does nothing, that removing the DriveThruRPG key yields `error`
rows rather than a crash, removing `SERPER_API_KEY` skips only that source with a
warning, and that no `product` row exists.

## Phase 4: MCP server, `update_product`, reads

- [x] FastMCP stdio server (`rpg-librarian serve`) with the logging middleware.
- [x] `update_product` exactly per the schema doc's signature: files by id; LLM
      dispositions `keep` / `superseded` / `discard` / `unfiled`; line and type
      resolution through names and aliases (case- and whitespace-insensitive);
      rejection with nearest matches unless `create_line` / `create_type`; product
      creation with near-match warning; sanitized-name collision check; `aliases`;
      `review_flag` mutually exclusive with a real disposition, auto-resolved with
      `note` on a later real call; one transaction, all-or-nothing; response with
      resolved coordinates, created entities, warnings, and the computed target
      folder.
- [x] Read tools, per the schema doc's "Reads": `report_file` (with the text-analysis
      hint, never the sample text), `report_product`, `report_line`, `list_unfiled`
      (folders with counts, then one folder's files; excludes duplicates, missing
      files, and files with an open review flag), `list_product_types`,
      `list_product_lines` (with alias `search`), schema discovery with the named
      example queries (needs enrichment, open review flags), and the ported read-only
      SQL tool. Every report carries `pending_changes` computed by the path function
      with a per-disposition breakdown.
- [x] `rename-file` MCP tool: rename one cataloged file within its current folder and
      update `file.relative_path`, rejecting missing files, paths, and disk or catalog
      collisions without overwriting.
- [x] CLI mirrors of `update_product`, the three reports, and the three list tools so
      the surface can be exercised without an MCP client.

Depends on: Phase 3 (reports show evidence), Phase 1 (path function). Outcome: an
LLM session can file a dump entirely in the database.

Verification: from the CLI mirror, list unfiled folders and one folder's files, file
that folder as one product with `keep`, confirm
rejection of an unknown line and success with `create_line`, confirm `keep` without
coordinates fails and writes nothing, confirm a `review_flag` then a later `keep`
resolves the flag, and confirm `pending_changes` counts the kept files. Then start
`serve` and call the same tools through an MCP client (Claude Code's MCP config or
`fastmcp` CLI) to confirm the stdio transport.

## Phase 5: `reorganize`

- [x] Compute desired location for every non-`unfiled` file: `keep` → target path;
      `duplicate` / `superseded` / `discard` → `<library>/.trash/<bucket>/` preserving
      the original relative path beneath it to avoid collisions.
- [x] `--dry-run` prints every planned move and lists any type folder that does not
      yet exist on the share as "new top-level folder".
- [x] Before each move verify size+mtime at the recorded source; on mismatch write an
      `error` row for stage `reorganize` and skip. Same-volume rename where possible;
      otherwise copy, verify by hash, then delete the source. Update `relative_path`,
      `root_id`, and `last_seen_at`; create directories as needed; never delete
      anything except a verified-copied source.
- [x] Idempotent: a second run with no catalog changes performs no moves.

Depends on: Phase 4 (something to move). Outcome: the share matches the catalog and
the dump folder holds only unfiled files.

Verification: `reorganize --dry-run` on the scratch catalog, inspect the listing, run
`reorganize`, confirm the library tree matches `type/line/[product/]file`, a
single-file product sits in its line folder, duplicates are under
`.trash/duplicates/`, and the dump contains only unfiled files; re-run and confirm no
moves; supersede one of a two-file product's files, re-run, and confirm the survivor
moved up into the line folder; modify a source file's mtime before a run and confirm
it is flagged, not moved.

## Phase 6: remove v1 and finish

- [ ] Delete `packages/rpg-librarian-mcp/` and its entries from the root
      `pyproject.toml` (ruff `src`, ty root, pytest testpaths); delete
      `scripts/migrate_legacy_catalog.py` and `scripts/fix_oversized_page_image_only.py`
      if they import v1; `uv lock`.
- [ ] Update `README.md`, `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` references to the
      new app and verbs; note that the library `CLAUDE.md` replacement is deferred.
- [ ] Record verification outcomes and limitations in `progress.md`; mark the item
      complete.

Depends on: Phases 0–5 verified. Outcome: one app, no v1 code, hooks green.

Verification: `uv sync`, `uv run ruff check`, `uv run ty check`, `uv run pytest`
(tools tests only), `uv run python scripts/check_migrations.py`, one full end-to-end
pass of `init` → `add-source` → `scan` → `enrich` → CLI `update_product` →
`reorganize --dry-run` → `reorganize` on a fresh scratch share.
