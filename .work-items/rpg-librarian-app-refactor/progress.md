# Progress

Current handoff for [plan.md](plan.md). Status: `implementing`. Phases 0 and 1 are
done; continue at Phase 2.

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

**Phase 1: catalog model, migrations, `init`, `add-source`** (done, uncommitted at time
of writing)

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

## Remaining

Phases 2 to 6 in `plan.md`. Before Phase 3, confirm the Serper API key returns
results in a manual request.

## Deviations

None from the plan; the two extras above are additions only.
