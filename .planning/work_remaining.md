# Work Remaining

Status as of 2026-07-28 (end of session). PyPI packaging work (prior session)
and the full test suite (this session) are both **done** — 22 tests passing,
`ruff`/`ty` clean. Almost nothing left except one inherently-manual
verification step (below) and the not-yet-started items further down.

## Done

- **`catalog.py`**, **`model/`**, **`db.py`**, **migration workflow**, **test
  library (`~/data/rpgtest`)**, **`commands/`**, **`mcp/update_catalog.py`** —
  all as previously documented from the prior session, still holds. See git
  history for the detailed session notes on `UpdateCatalogCommand` if needed;
  not repeated here.
- **PyPI packaging work (this session), in order:**
  1. **Relocated `alembic.ini` + `migrations/`** from the repo root into
     `src/rpg_librarian_mcp/alembic/` (a single relocation, not a copy — no
     duplicate config to keep in sync). Hatchling's existing
     `packages = ["src/rpg_librarian_mcp"]` wheel config bundles them
     automatically, confirmed via a clean `uv build`. `alembic.ini`'s
     `%(here)s`-relative `script_location` and `prepend_sys_path` needed no
     changes — both resolve relative to the ini's own new location.
  2. **`db.py`'s `_setup_db`** no longer does the old
     `Path(__file__).parent.parent.parent / "alembic.ini"` walk (which would
     have broken for any installed-package layout, not just wheels). It now
     locates the bundled config via
     `importlib.resources.files("rpg_librarian_mcp") / "alembic"`, wrapped in
     `resources.as_file(...)` **around the whole directory** (not just the
     `.ini` file) — deliberate, so that a rare zipped/zipimport install still
     has `migrations/` physically present next to the extracted `alembic.ini`
     when alembic resolves `script_location`. Verified end-to-end against
     `~/data/rpgtest`: backed up the existing `.catalog`, ran a fresh
     bootstrap, confirmed both migrations ran
     (`a0982134c448` → `f27fa1d64492`) and `alembic_version` landed at head,
     then restored the original test catalog.
  3. **Decided: auto-run stays create-only**, matching the original behavior
     exactly (`ensure_bootstrapped` only calls `_setup_db` when
     `catalog.db_path` doesn't exist yet — never re-checked/upgraded on every
     startup). Considered and explicitly rejected always-run-on-startup: for
     a personal single-user tool, a schema change silently applying itself
     the moment you start the server (no pause to back up first) was judged
     worse than requiring one explicit step after an upgrade.
  4. **Added `db.py:migrate_existing(catalog)`** as the explicit upgrade path
     for an already-existing catalog. `_setup_db` and `migrate_existing` both
     now call a shared `_run_alembic_upgrade(db_path)` helper — kept as two
     thin wrappers rather than one function because their guard conditions
     are opposite and mutually exclusive (create-if-missing vs.
     upgrade-if-present), and the separate names read more clearly at each
     call site than a single function with a mode flag.
  5. **Added `rpg-librarian-mcp --migrate`** (`__main__.py`, `argparse`).
     Resolves the target catalog via `Catalog.from_cwd()` — same "library
     root = cwd" rule the server itself uses, so it's run from inside the
     library directory, no path argument needed. On a missing catalog it
     exits cleanly via `SystemExit(str(e))` (one-line message, exit code 1,
     no traceback) rather than letting the `RuntimeError` propagate raw —
     this was flagged in code review and fixed same-session.
     **Verified both branches directly**: fresh directory with no `.catalog`
     → clean error, exit 1; `~/data/rpgtest` (already at head) → clean no-op,
     exit 0.
  6. **`migrations/env.py` now calls `catalog.py`'s existing `load_env()`**
     before reading `DATABASE_URL`, so a `.env` at/above the cwd is picked up
     automatically for `alembic` CLI commands — no more manually
     `source`-ing or inlining the env var. Verified with `alembic current`
     against the real `rpgtest` catalog using only `.env`, no shell export.
     Added a documented `DATABASE_URL` field to `.env.example` (marked
     dev-only, not read by the running server).
  7. **Verified empirically** (not just assumed) that Claude Code launches
     MCP stdio subprocesses with `cwd` matching wherever `claude` itself was
     started from — built a disposable probe MCP server, registered it at
     user/global scope, launched two non-interactive `claude -p` sessions
     from two different directories, confirmed each reported a different
     `os.getcwd()`. This confirms the "register once globally, `cd` into
     whichever library, launch `claude` there" pattern works for managing
     multiple libraries, as opposed to the `uvx --directory <path>` pattern
     (which pins one registration to one fixed library and needs a separate
     registration per library). Probe server and registration were cleaned
     up after the test — nothing left behind.
  8. **`claude.md`** gained a short "Development Notes" section documenting
     that `alembic.ini` now lives under `src/rpg_librarian_mcp/alembic/` and
     every `alembic` CLI call needs `-c` pointed at it explicitly.
  9. **`README.md`** rewritten: `Layout` section brought up to date with the
     actual current file tree (was still describing the pre-refactor
     `config.py`/`utils/` layout from an earlier session); `Installation`
     section now PyPI/`pipx`-oriented rather than clone-only; new
     `Development` section covers `DATABASE_URL` setup and the `-c` flag
     requirement for both `revision --autogenerate` and `upgrade`; the
     `## Database setup` section documents `rpg-librarian-mcp --migrate` as
     the upgrade-an-existing-catalog step, replacing the earlier draft's
     raw, checkout-only `alembic -c ... upgrade head` instruction (which
     would not have worked for a `pipx`-installed user, since there'd be no
     `src/` tree to point `-c` at).
  10. **Also decided (earlier this session, small item, unrelated to the
     packaging work)**: `mcp/update_catalog.py`'s JSON response now
     explicitly converts nested `ProcessingError` NamedTuples via
     `{**result._asdict(), "errors": [e._asdict() for e in result.errors]}`,
     so errors serialize as keyed objects (`{"path": ..., "reason": ...}`)
     rather than positional 2-tuples — resolves the item that was flagged
     but left undecided at the end of the previous session.
- Whole-repo `ruff check`, `ty check`, and `pytest` all still pass clean
  after all of the above (checked incrementally after each file change this
  session, not just once at the end).
- **Test suite written (this session)**, 22 tests total, all passing:
  - `tests/test_should_process_row.py` — the four-way `_should_process_row`
    decision (force, no-existing-entry, mtime-newer, mtime-not-newer) as
    pure-function tests against in-memory `Entry` objects, no DB involved.
  - `tests/test_update_catalog_command.py` — new-file creation, deletion
    reconciliation (including the sibling-folder false-positive case),
    force-reprocess, skip-when-unchanged, non-recursive scoping (both
    "doesn't descend" and "doesn't delete a sibling folder's entries"),
    new-vs-existing error-routing split (`_record_error` writes no DB row
    for a brand-new file, does write/clear one for an existing file —
    covers the `_clear_stale_error` cycle too), `max_errors` capping, FK
    cascade (deleting a file whose entry has an `Error` row removes both),
    and a progress-throttling regression test (150 files compressed into
    ≤101 `report_progress` calls). The doc's earlier "literal `%`/`_` in a
    folder name" concern turned out to be moot: the deletion-reconciliation
    scan filters in Python (`Path.is_relative_to`/`==`), not via a SQL
    `LIKE`, so those characters were never special to begin with — no test
    needed for it.
  - `tests/test_db_migrate.py` — `migrate_existing` on a missing catalog
    (raises), an up-to-date catalog (no-op), and a stale catalog stamped at
    `a0982134c448` (actually upgrades to `f27fa1d64492`).
  - `tests/test_main.py` — `--migrate` flag dispatch, both branches (clean
    `SystemExit` on no catalog, success on an existing one).
  - `tests/conftest.py` — autouse fixture forcing `DATABASE_URL=""` for
    every test. Needed because a real dev-only `.env` at the repo root (with
    `DATABASE_URL` pointed at a scratch catalog used for manual
    verification earlier this session) was getting picked up by `env.py`'s
    upward `.env` search, since `pytest`'s `tmp_path` lives under
    `.pytest-tmp` inside the repo — silently redirecting every test's
    alembic calls to that scratch DB instead of the test's own tmp dir.
  - **Found and fixed a real bug in the process**: `_should_process_row`
    compared a tz-aware `file_time` against `existing.updated_at`, which
    SQLite/SQLAlchemy returns naive on read — `TypeError` on every
    mtime-newer comparison against an already-catalogued row. Fixed at the
    type level: `model/core.py` gained a `UTCDateTime` `TypeDecorator`
    (same pattern as the existing `ParentPathType`) that reattaches
    `tzinfo=UTC` on every read and rejects naive writes; `EntityBase.
    created_at`/`updated_at` now use it via `sa_type=UTCDateTime`. No
    migration needed — the underlying stored bytes are unchanged, only the
    Python-side round-trip contract.

## Next

1. **End-to-end manual run against `~/data/rpgtest`** — the one item from
   the original test list that's inherently manual (a real disk / real
   library sanity check), not something to automate. Still not done this
   session.

## Not started / not designed yet

- No MCP tools exist yet for the actual identification/enrichment work
  (ISBN lookup, OCR) that `Error`'s `ErrorStage` enum is meant to grow
  beyond `populate_file_data` for eventually.
- `commands/__init__.py` just does direct imports/`__all__`, no
  registration/discovery pattern — still fine with only one command, revisit
  if a second command shows a real need.
- No PyPI publish has actually happened yet — everything above makes the
  package *ready* to publish, but `pipx install rpg-librarian-mcp` itself
  hasn't been tried against a real published (or TestPyPI) release, only
  against a local `uv build` wheel's contents.
