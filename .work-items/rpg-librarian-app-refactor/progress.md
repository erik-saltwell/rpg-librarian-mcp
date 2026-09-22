# Progress

Current handoff for [plan.md](plan.md). Status: `implementing`. Phases 0 to 5 are
done; continue at Phase 6 (remove v1 and finish). Manual-testing checkpoint 3 is next: run
`reorganize --dry-run`, then `reorganize`, on a *copy* of a small dump and part of the library. **Manual-testing checkpoint 2 is now:** register
the server with Claude Code and file a few products (see the app README). **Manual-testing checkpoint 1 is now:** run `init`,
`add-source`, and `scan` against one real dump on the share before Phase 3 starts.

## Completed

**Bundled agent skills** (completed 2026-09-22)

- Packaged `process-batch` and `review-items` as app resources. `init` seeds both
  skills into the initialized library's `.claude/skills/`, `.codex/skills/`, and
  `.gemini/skills/` locations, leaving an existing local skill file untouched.
- Verified a scratch initialization installs all six files, a second run is idempotent,
  and the built wheel includes both bundled resource files.

**MCP `rename-file` tool** (completed 2026-09-22)

- Added `rename-file(file_id, new_name)` to the new app's FastMCP server. It renames
  only the basename within the file's existing source and folder, updates the catalog,
  refuses missing/colliding destinations and path-like names, and attempts to restore
  the disk name if the database commit fails.
- Verified against a migrated scratch catalog and real scratch files, including path
  traversal and overwrite rejection; confirmed FastMCP advertises the exact tool name.
- `uv run ruff check` and `uv run ty check` pass; the complete test suite passes with
  324 tests.

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
  `file_text`, `file_text_analysis`, `error`, `review_flag`. Integer primary keys.
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
  as `calls.log` and `files.log`, later replaced by the single `events.log`, see "Logging" below), and
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
  google, text_analysis), `isbn_lookup.py` (ported from v1; now records which provider found the
  record), `text_analysis.py` (v1's judgment prompt as a plain format string, model from
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

**Rename after Phase 3: the LLM enrichment is "text analysis".** The table, class,
stage, and `--source` value now name where the data comes from (the stored text sample)
rather than how it is produced: `file_llm_extraction` → `file_text_analysis`,
`FileLlmExtraction` → `FileTextAnalysis`, stage and source `llm` → `text_analysis`,
`enrichment/llm.py` → `enrichment/text_analysis.py`. `RPG_LIBRARIAN_LLM_MODEL` keeps its
name because it does select a model. Migration `0003` renames the table and relabels
existing `llm` error rows; checked on a populated copy of the test catalog (rows survive,
stage relabelled, downgrade restores the old names) and by `check_migrations.py`.

**Phase 4: MCP server, `update_product`, reads** (done, uncommitted)

- `services/`: `update_product.py`, `reports.py`, `lists.py`, `schema.py` (describe + the
  ported read-only SQL guard), `pending.py`, `names.py` (case- and whitespace-insensitive
  matching, nearest-name suggestions, near-match warnings), `serialize.py`. Pure functions
  over a session; both front doors call them.
- `server/`: FastMCP stdio server (`tools.py` with LLM-facing tool descriptions,
  `middleware.py` logging every call to `events.log` with transport `mcp`, workflow
  `INSTRUCTIONS` in `__init__.py`). It migrates the catalog once at startup and opens
  sessions with `migrate=False` per call. The banner and PyPI update check are off.
- Nine tools: `list_unfiled`, `list_product_types`, `list_product_lines`, `report_file`,
  `report_product`, `report_line`, `describe_schema`, `query`, `update_product`.
- CLI mirrors (`commands/tools.py`): `update-product`, `report-file`, `report-product`,
  `report-line`, `list-unfiled`, `list-types`, `list-lines`, printing JSON; errors go to
  stderr with exit 1. `serve` is the verb for the server and is not wrapped in a call
  tracker.
- `paths.py`: trash buckets and `desired_trash_path`, shared with Phase 5.
- Dependency added: fastmcp.

**Logging: one event stream, `logs/events.log`** (after Phase 4, uncommitted)

The wide-event logs now follow one pattern for batch verbs, so a run reads top to bottom:

1. `call_started`: once, when the verb begins, with its arguments.
2. `file`: exactly one per file handled (`success`, `error`, or `skipped`), carrying
   everything known about it: path, duration, hashes, page counts, `action` (`new`,
   `changed`, `retry`, `forced`, `moved`, `unchanged`), the enrich `source`, and the error.
3. `call_finished`: once, when the verb ends, with totals and `outcome`. Written on failure
   and on Ctrl-C too, so a dying run says how it ended. A `call_started` with no
   `call_finished` means the process was killed hard. `enrich` totals are per source
   (`eligible`, `attempted`, `with_results`, `empty`, `errors`, `stopped_reason`,
   `skipped_reason`).

An MCP tool call is a single `call_finished` event (no start, no per-file events).
Trade-off accepted: the old separate `started` line per file is gone, so if a run hangs,
the log no longer names the file in flight (the progress bar does; the last `file` event
names the last file *finished*).

Found by auditing your real logs: no start entry existed for any verb, files had two lines
each (110 for 55), the `started` lines carried no `source` (useless for `enrich`), and an
interrupted `enrich` run left a dangling `started` with nothing to say the run had begun or
died. Fixed along the way: a file whose extraction failed without raising was logged
`success` (it is now `error`); an errored file being retried was labelled `changed` (now
`retry`); a moved file was `new` (now `moved`); and scan error text, which is also stored in
the `error` table, named the throwaway local copy (`/tmp/rpg-librarian-scan-…`) instead of
the file on the share. Verified on scratch shares (three scan runs: new, unchanged,
hand-moved; a corrupt file, a duplicate) and with fake `enrich` sources (success, empty,
failure, fatal stop, Ctrl-C), plus one real MCP session.

**Enrich query quality, after reviewing your real run** (uncommitted)

Reviewing the 55-file enrich run found two kinds of noise, both now fixed:

- **Junk hits from category folders.** DriveThruRPG and RPGGeek's ladder fell back to
  top-level folder names, so "system agnostic" returned the same unrelated product for ~26
  audio, mesh, and text files and "Maps" did for the six `.ai` files. These sources now run
  only for product documents: PDFs that are not `.ai`. That is 20 of the 55 files, down from
  55, which also saves API time.
- **Google queries built from junk or generic titles** ("Sheet1-1", "interior.indd",
  "Series Worksheet"). For product documents the top-level folder is now appended. Live
  comparison of three candidate rules on eight representative files showed the append is a
  big win when that folder is a product and harmful when it is a category, which is why it
  is limited to product documents. My earlier recommendation ("append it always") was wrong
  for pack files and was narrowed on that evidence.
- Also: an embedded title ending in a file extension is ignored; DriveThruRPG order ids
  (`(8113103)`) are stripped from filename stems; a parent folder that repeats the filename is
  dropped. `enrich --force` now also removes a source's stale rows for files it no longer
  wants.
- Known remaining weakness: four `BattlfinderAm* copy.pdf` map PDFs in a `Maps` folder still
  count as product documents (they are PDFs), and a category-named top-level folder above a
  real product (`system agnostic/pdf/John Wick Presents/Play Dirty`) is still appended.

**Phase 5: `reorganize`** (done, uncommitted)

- `services/placement.py`: `compute_placements` (destination and settled-or-not for every
  filed file), now used by `pending_changes` too, so reports and dry runs cannot disagree.
- `commands/reorganize.py` with `--dry-run` and `--limit N`; rules are recorded in
  `catalog-schema.md` under "What `reorganize` does with the plan".
- Decisions taken (the defaults offered before building): empty folders are removed;
  colliding targets are refused for both files; kept files already in the library are
  moved to their computed location.
- Logging follows the same start / one-event-per-file / end pattern; file events carry
  `action` (`moved`, `trashed`, `blocked`), `dest`, and `method` (`rename` or `copy`).

## Deviations from the plan and schema doc

- **Nullable `sha256`, `mime_type`, `media_type` on `file`**, so a file row (and its
  `error` rows) can exist before extraction succeeds. Recorded in `catalog-schema.md`.
- **`created_at` instead of `first_seen_at` (file) and `added_at` (root)**: the base class
  already provides it. Recorded in `catalog-schema.md`.
- **`product.year` is text** (as in v1), since a year range or a bare year both occur.
- **Stage names** for `error` rows: `scan`, `metadata`, `text`, `dtrpg`, `rpggeek`,
  `isbn`, `google`, `text_analysis`, `reorganize`.
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
- **Phase 4 rules the docs did not settle** (now in `catalog-schema.md`): `unfiled` clears
  the product link; `discard`/`unfiled` reject coordinates; a review flag leaves the
  disposition unchanged; duplicates and missing files cannot be filed; types get the
  same folder-collision check; a 500-file cap per call; the trash path scheme.
- **`--force` on `enrich`** (not in the plan) refetches files a source already covers.
- **The text-analysis source writes an empty row for a file with no sampled text**, without calling
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
  `logs/calls.log` and `logs/files.log` (since replaced by `events.log`) were written with the expected fields.
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
- **text analysis** (then called `llm`)**:** 2 files, 0 errors. Both got `possible_system` and a sensible description
  (`Blood and Bone`, and a summary of the Red Road adventure).
- **isbn:** with your `GOOGLE_BOOKS_API_KEY` set, Google Books returned 403 and the source
  stopped after one file with the error recorded (v1's stop-on-Google-Books-unusable
  rule). With that key blanked, Open Library/Wikidata ran: 5 files, 1 record (a stand-in
  ISBN, found via Wikidata) and 4 empty results (the catalog's real ISBNs, including
  The Sprawl's `9780473348274`, are not in those services). The earlier error row for the
  file was cleared when it later succeeded.
- **rpggeek:** first run: the source stopped after one file, reporting the bearer token
  rejected. **That diagnosis was wrong.** `rpggeek.com` answers API calls with a Cloudflare
  bot challenge (403, HTML, `cf-mitigated: challenge`) whatever the token, while the same
  token returns 200 on `boardgamegeek.com/xmlapi2`, which serves `type=rpgitem`. Fixed in
  the tools package (base URL, and a Cloudflare challenge now reports as a service error
  instead of "bad token"). Verified live afterwards: 3 of 3 files with results and
  details, 0 errors.
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

### Phase 4 verification

Against copies of your `.test` catalog (yours was not modified):

- **Worklist:** on the real 55 files across three dumps, `list_unfiled` returned the full
  folder tree with direct and subtree counts; a folder view returned its own files (with
  page counts and hints) plus subfolders; `recursive` returned the whole subtree; a folder
  present under several roots asked for `root_id`.
- **`update_product` rule matrix (in-process, ~45 cases):** every rejection left the
  database exactly unchanged (a snapshot of row counts and every file's disposition and
  product was compared before and after each call): keep without coordinates, empty ids,
  partial coordinates, `duplicate` as a disposition, coordinates with discard, a flag with
  keep, neither disposition nor flag, aliases without coordinates, an unknown metadata
  field, an unknown file id, an unknown type (suggests the closest), an unknown line,
  an alias owned by another line, sanitized-folder collisions for types, lines, and
  products, an automatic duplicate, a missing file, both together, and 501 files.
  Successes: create line + product with aliases and metadata; reuse by other case and
  spacing; resolve by alias; the single-file rule (target folder gains a product folder
  at the second kept file); a near-match product warning; `create_type` implying a new
  line; flag open, update-in-place, exclusion from the worklist, `include_flagged`,
  auto-resolution with a note; superseded with and without coordinates; discard; and
  `unfiled` clearing the link.
- **Reports:** `report_file`, `report_product`, and `report_line` matched the database;
  `report_file` carries the hint and identifiers and provably contains no sample text.
- **`pending_changes`:** counts kept files not at their target; drops when a file sits at
  its computed target; a superseded file in the right trash bucket is settled and in the
  wrong bucket is pending; `desired_trash_path` is stable under re-application.
- **Real MCP over stdio** (FastMCP client against `rpg-librarian serve`): 9 tools with
  correct schemas (the `disposition` enum, `file_ids` required); every tool called; errors
  arrive as tool errors with the same messages; `query` rejected `delete`, `drop`,
  `pragma`, a second statement, and a `WITH ... DELETE` (refused by SQLite itself), and
  capped 2,000 rows at 500 with `truncated`; every call was logged to the event stream with
  transport `mcp`; the server exits within seconds of the client disconnecting; its stderr
  has no banner and no network update check.
- **CLI mirrors:** exit 0 with JSON, exit 1 with a message on stderr; files filed through
  `update-product` no longer appear in `list-unfiled`.
- `uv run ruff check`, `ruff format`, `ty check`: pass.

Not exercised: a real LLM session driving the tools (that is manual checkpoint 2), and
large catalogs (the report and worklist queries load whole tables into Python).

### Phase 5 verification

On a scratch share: a library, `dump_a` on the same volume, and `dump_b` in `/dev/shm`, a
separate tmpfs, so the cross-volume path ran for real. Products were filed through the real
`update_product` service. 38 checks, all passing:

- **Dry run:** grouped plan listing 9 moves and 2 blocked, the new top-level folders
  `games` and `maps`, and *nothing* changed on disk or in the catalog.
- **Real run:** single-file products in their line folder; a two-file product in a product
  folder; the cross-volume file copied, verified, and its source removed with no partial
  file left; duplicate, discard, and superseded files under `.trash/duplicates/`,
  `.trash/discarded/`, `.trash/superseded/`; two READMEs wanting the same target both
  refused and left in place; the unfiled file untouched; empty folders removed while the
  dump root and `.trash` survived; catalog rows repointed into the library.
- **Idempotent:** a second run moved nothing (9 already in place).
- **Supersede one of two kept files:** the survivor moved up into the line folder, the other
  went to the trash, and the emptied product folder was removed.
- **Changed source:** a file whose modified time no longer matched the scan was flagged and
  not moved, and moved after a rescan.
- **Existing destination:** an untracked file at the target was left untouched, and the
  error row said the destination exists.
- **Crash recovery:** a hand-moved file was refused as not at its recorded path, `scan`
  re-identified it as a move (no duplicate), and `reorganize` then found it settled.
- **Chain:** a file wanting a path held by a file about to move waited its turn; both
  moved and no content was lost.
- **`--limit 2`** moved exactly two; the next run finished the rest.
- **A failed copy verification** (recorded hash deliberately wrong): the source stayed
  byte-identical, nothing landed at the destination, no partial file remained, an error
  was recorded, and the catalog row was unchanged.
- A dry run against a copy of the real session catalog said "nothing to do" (nothing has
  been filed in it yet).

Found and fixed during verification: a stale `reorganize` error row survived after the file
it described was fixed and rescanned, because settled files are never revisited. The errors
are now a per-run snapshot.

Not exercised: a real network mount (SMB rename semantics, timestamp granularity), permission
errors, and files above a few MB (the copy path re-reads the whole file to verify it).

## Remaining

Phase 6 in `plan.md`. **Checkpoint 3 first**, on copies. Still unverified against real results: the `isbn` source
with a working Google Books key, and the `google` source (Serper). **Checkpoint 2 first:** a short real session. Note that your
Claude Code config may already register a server named `rpg-librarian` (the v1 server); use
a different name (the README uses `rpg-librarian-app`) until v1 is removed in Phase 6. **Phase 4's scope changed by agreement after Phase 3:** the
MCP surface is now nine tools, not six. Added: `list_unfiled` (the worklist; excludes
duplicates, missing files, and files with an open review flag), `list_product_types`, and
`list_product_lines` (with an alias `search`). Reports return the text-analysis hint but
never the sampled page text. Recorded in `intent.md`, `catalog-schema.md` ("Reads"), and
`plan.md` (Phase 4). **Before manual-testing checkpoint 2:** get a fresh RPGGeek
bearer token, a working Google Books key (or unset it), and a Serper key, then run
`enrich` on the real catalog; those three sources are unverified against real results. Before Phase 3, confirm the Serper API key returns
results in a manual request.

## Deviations

None from the plan; the two extras above are additions only.
