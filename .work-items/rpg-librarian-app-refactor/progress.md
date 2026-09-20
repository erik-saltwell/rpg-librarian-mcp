# Progress

Current handoff for [plan.md](plan.md). Status: `implementing`.

## Completed

**Phase 0: app scaffold and tooling** (done, uncommitted at time of writing)

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

## Remaining

Phases 1 to 6 in `plan.md`. Before Phase 3, confirm the Serper API key returns
results in a manual request.

## Deviations

None from the plan; the two extras above are additions only.
