# Progress

Current handoff for [plan.md](plan.md). Status: `implementing`. Phases 0 to 3 are
done; continue at Phase 4 (the MCP server and `update_product`). **Manual-testing checkpoint 1 is now:** run `init`,
`add-source`, and `scan` against one real dump on the share before Phase 3 starts.

## Completed

**Phase 0: app scaffold and tooling** (done, committed as `2218ec2`)

- Created `apps/rpg-librarian/` with `pyproject.toml` (hatchling, `python-dotenv` and
  `rpg-librarian-tools` only; later phases add their own dependencies), `README.md`,
  `src/rpg_librarian/{__init__,__main__,config}.py`, and `tests/conftest.py`.
- `__main__.py` has the six verbs (`init`, `add-source`, `scan`, `enrich`,
  `reorganize`, `serve`) as stubs that print "not implemented yet" with the resolved
  catalog path and exit 2. `--catalog` is defined on each subparser via a shared
  parent parser.
- `config.py`: `load_env()` (ported from v1: `find_dotenv()`, existing variables win)
  and `resolve_catalog_path()` with precedence `--catalog`, then
  `RPG_LIBRARIAN_CATALOG`, then `./catalog.db`.
- Root `pyproject.toml`: added `./apps/rpg-librarian/{src,tests}` to the ty roots and
  `apps/rpg-librarian/tests` to pytest `testpaths`. All four wiring points are now done.
- Extras beyond the plan: `catalog.db` added to `.gitignore`; `RPG_LIBRARIAN_CATALOG`
  documented in `.env.example` under a new section for the app.

**Phase 1: catalog model, migrations, `init`, `add-source`** (done, committed as `f08a000`)

- `model/`: one file per class, matching v1's layout. Tables `root`, `product_type`,
  `product_line`, `product_line_alias`, `product`, `file`, `file_metadata`,
  `pdf_metadata`, `image_metadata`, `audio_metadata`, `video_metadata`, `mesh_metadata`,
  `file_text`, `file_llm_extraction`, `error`, `review_flag`. Integer primary keys.
  `core.py` holds the UTC datetime type, an enum-as-text type (one subclass per enum,
  with `MediaType` tolerant of unknown stored values), and the two base classes.
  Constraints: unique `(root_id, relative_path)`, `keep` requires `product_id` (a CHECK),
  unique lines per type, products per line, aliases per line, and a partial unique
  index allowing one open review flag per file.
- Evidence tables (DriveThruRPG, RPGGeek, ISBN, `google_search_result`) are deliberately
  not here: their columns are settled and migrated in Phase 3, per the plan.
- `alembic/` under the app: `alembic.ini`, `env.py`, `script.py.mako`, and migration
  `0001_initial_catalog` generated from the models, then edited so it depends on plain
  SQLAlchemy types only, not app code. `db.py` upgrades on every session open, never
  creates the catalog (only `init` does), and commits on a clean exit.
- `scripts/check_migrations.py` now points at the new `alembic.ini`. v1's chain is no
  longer checked by the hook (it is frozen and goes in Phase 6).
- `paths.py`: `sanitize_name`, `folder_key`, `kept_file_count`, `target_relative_path`.
- `product_types.py`: the seed list. `errors.py`: `UsageError` (CLI prints it, exit 1).
- `init --library PATH` and `add-source PATH [--label]` implemented as specified;
  `scan`, `enrich`, `reorganize`, `serve` remain stubs.

**Phase 2: `scan`** (done, uncommitted at time of writing of Phase 3)

- Ported from v1: `infrastructure/isolated_worker.py` (unchanged), the six media
  extractors and `MetadataExtractor` (imports retargeted; SVG now routed by the
  `vector` media type, which is what the tools package actually reports),
  `observability.py` (renamed entry → file; logs live in `logs/` beside the catalog
  as `calls.log` and `files.log`; the MCP middleware waits for Phase 4), and
  `progress.py` (synchronous rich bar).
- `infrastructure/walk.py`: skips dotfiles, `.trash`, and `agents.md`/`claude.md`.
- `commands/scan.py`: `Scanner` with `collect` → `mark_missing` (all reachable roots,
  before any processing) → `process_root`. Per file: stat, skip rule, copy local,
  `inspect_file`, move detection, upsert, clear errors and scan-owned rows, extract
  (embedded + per-media; PDFs also barcode, text sample keyed by 1-based page, ISBN/ISSN
  from barcode → text → embedded metadata), hash join, delete local copy, commit. Every
  file is its own transaction so a crash keeps progress.
- `scan [--root PATH] [--force]` wired in `__main__.py`, which now also configures the
  wide-event logs and wraps every verb in a `CallTracker`.
- Dependencies added to the app: mutagen, pymediainfo, pillow, pymupdf, trimesh, lxml,
  networkx, pebble, rich, structlog. Dropped from v1's list: pypdfium2 and scipy
  (nothing imports them; the mesh extractor avoids the convex hull).

**Phase 3: `enrich`** (done, uncommitted)

- Tools package: `rpg_librarian_tools.google.search(query, api_key, num=5, *, policy)`
  calling Serper.dev (`POST /search`, `X-API-KEY`), returning `SearchHit(position, title,
  url, snippet)`; 401/403 → `AuthenticationError`, 402 or a 400 mentioning credits →
  `RateLimitError`, 429/5xx retried per policy. Documented in the tools README.
- Model + migration `0002_add_evidence_tables`: `dtrpg_result`, `rpggeek_result`,
  `isbn_result`, `google_search_result`, all subclasses of a new `EvidenceBase` (`file_id`
  key, `query`, JSON `results`, `fetched_at`). Frozen to plain SQLAlchemy types like 0001.
- `enrichment/`: one module per source behind a small `Source` protocol (`name`, `stage`,
  `table`, `unavailable_reason`, `wants`, `fetch`), `queries.py` (file context, name and
  Google queries, the query ladder), `registry.py` (run order: isbn, dtrpg, rpggeek,
  google, llm), `isbn_lookup.py` (ported from v1; now records which provider found the
  record), `llm.py` (v1's judgment prompt as a plain format string, model from
  `RPG_LIBRARIAN_LLM_MODEL`, default `gpt-5.6-luna`, litellm imported lazily).
- `commands/enrich.py` and `enrich [--source S]... [--limit N] [--force]`. Eligible files:
  not `duplicate`, not missing, and with no row yet for that source. Per file: its own
  transaction; success writes/merges the evidence row and clears any error row; a
  failure writes an `error` row and moves on; a `FatalSourceError` (bad key, exhausted
  quota) writes the error row and stops that source for the run. Sources without a
  credential are skipped with a message. Shared `error_rows.py` helpers, now also used
  by `scan`.
- `scan` change: evidence rows are dropped only when a file's content changed, not on
  every re-extraction.
- Dependencies added: litellm, isbnlib, and setuptools<82 (isbnlib imports
  `pkg_resources`).

## Deviations from the plan and schema doc

- **Nullable `sha256`, `mime_type`, `media_type` on `file`**, so a file row (and its
  `error` rows) can exist before extraction succeeds. Recorded in `catalog-schema.md`.
- **`created_at` instead of `first_seen_at` (file) and `added_at` (root)**: the base class
  already provides it. Recorded in `catalog-schema.md`.
- **`product.year` is text** (as in v1), since a year range or a bare year both occur.
- **Stage names** for `error` rows: `scan`, `metadata`, `text`, `dtrpg`, `rpggeek`,
  `isbn`, `google`, `llm`, `reorganize`.
- **Both apps cannot be imported in one process**: v1 and the new app share SQLModel's
  global metadata and both define `product` and `error`. Nothing imports both; v1 goes
  in Phase 6.

- **Skip rule also retries errors**: a file with an `error` row for a scan stage, or
  with no `sha256` yet, is reprocessed even when size and mtime match. The schema doc
  describes the skip rule only in terms of size and mtime.
- **Missing detection runs before processing**, across all reachable roots, so moves
  are recognised in the same run. Recorded in `catalog-schema.md`.
- **`.trash/` rows** are neither walked nor marked missing but stay in the hash join,
  and a trashed library row wins that join, so a discarded file reappearing in a dump
  is flagged `duplicate`. Recorded in `catalog-schema.md`.
- **DriveThruRPG and RPGGeek use a query ladder, not the single name query.** Found in
  live testing: both match every word, so `Fasano Blood And Bone Core Rules` returned 0
  hits while `Blood and Bone` found the right product. Google keeps the agreed single
  rule. Recorded in `catalog-schema.md`.
- **The RPGGeek token is required**, not optional: RPGGeek now rejects unauthenticated
  calls, so the source is skipped without `RPGGEEK_BEARER_TOKEN`.
- **`--force` on `enrich`** (not in the plan) refetches files a source already covers.
- **The LLM source writes an empty row for a file with no sampled text**, without calling
  the model, so it is not retried every run.
- **Changed content at a path** also resets any rows that were `duplicate` of it.
- **No separate `clear-metadata` verb**: `--force` covers it, as the plan proposed.

## Verification (actual outcomes)

- `uv sync`: installed `rpg-librarian==0.1.0` from the workspace.
- `uv run rpg-librarian --help`: lists the six verbs.
- `rpg-librarian scan --catalog /tmp/x.db`: prints the stub message with `/tmp/x.db`,
  exit 2. `RPG_LIBRARIAN_CATALOG=/tmp/env.db ... init` resolves the env path. From
  `/tmp` with neither set, `serve` resolves `/tmp/catalog.db`. No verb: argparse error,
  exit 2.
- `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`: all pass.
  `uv lock --check`: resolves 138 packages.
- `uv run pytest --collect-only apps`: "no tests collected", as intended (no tests are
  added by policy). The full `uv run pytest` was not run in this phase; the three
  collection errors seen earlier in `packages/rpg-librarian-mcp/tests/` are v1's and
  were not investigated.

### Phase 1 verification

- `uv run python scripts/check_migrations.py`: builds a fresh database from the
  migration alone, and `alembic check` reports "Migrations match the SQLModel schema".
- On a scratch share (library, `dump_A`, `dump_B`): `init` created the catalog, seeded
  all 10 types, and registered the library; re-running `init` was a no-op; `init` with a
  different or non-existent directory was refused (exit 1); `add-source` registered two
  staging roots, treated a repeat as a no-op, and refused a path inside a root, a path
  containing a root, and a missing catalog (no catalog file was created by accident).
- Constraints checked directly in SQLite with foreign keys on: `keep` without a product
  rejected; duplicate `(root_id, relative_path)` rejected while the same path under
  another root is accepted; a bad `root_id` rejected; a second open review flag rejected
  and accepted again after the first was resolved.
- ORM round trip: enums, UTC-aware datetimes, JSON page samples, and an unrecognized
  stored `media_type` reading back as `unknown`. Path function: two kept files give
  `maps/<line>/<product>/f.pdf`, one gives `maps/<line>/f.pdf`; `"Foo: Bar"` and
  `"foo- BAR"` collide on `folder_key`; `CON` becomes `CON_`; 300 characters truncate
  to 200.
- `uv run ruff check`, `uv run ruff format`, `uv run ty check`: pass. Not run: a
  scan-free `uv run pytest` (no tests added, by policy).

### Phase 2 verification

Against a generated scratch share (library with one PDF; dump with an 8-page text PDF
carrying an ISBN and duplicating the library PDF, a one-page image-only PDF, a PNG, an
SVG, a WAV, an STL, a dotfile, and a `.trash/` folder). Tesseract is installed locally.

- First scan: 7 files processed, 0 errors. Every extractor wrote its row (PDF page
  counts and `likely_image_only` on the scanned page, PNG 64×32 with alpha, SVG 10×20,
  WAV 1.0 s, STL 10×20×30 mm). ISBN `9780306406157` found in the text sample; the
  sample holds pages 1–5 and 7–8. The dump copy of the PDF became `duplicate` of the
  library copy. The dotfile and `.trash/` were not walked. No temp directory was left.
  `logs/calls.log` and `logs/files.log` were written with the expected fields.
- Re-scan: 7 skipped. Touching one mtime: exactly 1 reprocessed. `--force`: all 7.
- Move by hand within the dump, and dump → library: both recognised as moves (row keeps
  its id and disposition, path updated), not duplicates.
- Deleting a file: marked missing. Replacing a file's bytes: media type re-detected,
  a `discard` disposition reset to `unfiled`.
- A corrupt PDF: `error` row at stage `metadata`, and the file is reprocessed on the
  next run rather than skipped.
- Unreachable root: warning printed, no rows marked missing.
- A trashed row (inserted by hand) was not marked missing and won the hash join against
  a fresh copy of the same bytes in the dump, which was flagged `duplicate`.
- `--root PATH` limited the scan to one root.
- `uv run ruff check`, `uv run ruff format`, `uv run ty check`: pass.

Not exercised: video (no sample generated), 3MF meshes, password-protected PDFs, a real
SMB mount (timestamp granularity and copy speed are exactly what manual checkpoint 1
should cover), and the worker pool's crash/timeout path.

### Phase 3 verification

Live, against a **copy** of your `.test` catalog (your catalog was not modified) with
your `.env` keys:

- **dtrpg:** with the single name query, 3 of 3 files returned 0 results. After the
  ladder, 7 of 7 PDFs returned results; the winning query was the top-level folder
  (`Blood and Bone`, `Daring Comics Role Playing Game`) and the right product (Arcana
  Games, Daring Entertainment) appeared in the results.
- **llm:** 2 files, 0 errors. Both got `possible_system` and a sensible description
  (`Blood and Bone`, and a summary of the Red Road adventure).
- **isbn:** with your `GOOGLE_BOOKS_API_KEY` set, Google Books returned 403 and the source
  stopped after one file with the error recorded (v1's stop-on-Google-Books-unusable
  rule). With that key blanked, Open Library/Wikidata ran: 5 files, 1 record (a stand-in
  ISBN, found via Wikidata) and 4 empty results (the catalog's real ISBNs, including
  The Sprawl's `9780473348274`, are not in those services). The earlier error row for the
  file was cleared when it later succeeded.
- **rpggeek:** your `RPGGEEK_BEARER_TOKEN` is rejected; the source recorded one error row
  and stopped, as designed. Unauthenticated calls are also rejected. So this source has
  **not** been exercised against real results.
- **google:** there is no `SERPER_API_KEY` in `.env`, so the source has **not** been run
  against Serper. The client was checked against a mock transport: request shape (POST,
  `X-API-KEY`, `{"q","num"}`), parsing of `organic`, missing/extra fields, 401, exhausted
  credits (400/402), a persistent 429, a persistent 500, a non-credit 400, and a retry
  after two 503s. Serper's real response shapes and its out-of-credits status code are
  from memory and unverified.
- **Behavior with fake sources on a scratch share** (6 files, one a duplicate): the
  duplicate is excluded; a second run does nothing; `--limit 2` then the rest covers
  exactly the remainder; empty results write rows and are not re-queried; one failure
  writes an `error` row and no evidence row and only that file is retried, clearing the
  error; a fatal error stops the source after the failing file; a missing credential
  skips the source; `--force` refetches all; a same-content rescan keeps evidence and a
  changed-content rescan drops it.
- `uv run ruff check`, `ruff format --check`, `ty check`, `check_migrations.py`, and the
  tools package's existing tests (3): pass.

## Remaining

Phases 4 to 6 in `plan.md`. **Before manual-testing checkpoint 2:** get a fresh RPGGeek
bearer token, a working Google Books key (or unset it), and a Serper key, then run
`enrich` on the real catalog; those three sources are unverified against real results. Before Phase 3, confirm the Serper API key returns
results in a manual request.

## Deviations

None from the plan; the two extras above are additions only.
