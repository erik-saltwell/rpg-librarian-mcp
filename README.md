# rpg-librarian-mcp

MCP server (stdio) for cataloging and organizing a digital RPG archive.

## Layout

src/rpg_librarian_mcp/
  main.py       entry point (rpg-librarian-mcp / python -m rpg_librarian_mcp)
  server.py         builds the FastMCP server, registers tools, runs stdio
  catalog.py        .env loading + Catalog (library root = cwd)
  db.py             engine/session setup, auto-bootstraps a new catalog's db
  alembic/
    alembic.ini      bundled into the package so migrations work post-install
    migrations/
  model/             SQLModel tables (Entry, Error, MediaType)
  commands/          CommandProtocol + per-tool business logic (UpdateCatalogCommand, ...)
  mcp/
    init.py      REGISTRARS list -- add new tool modules here
    status.py        librarian_status
    update_catalog.py
    directory_status.py  list_directory_entries, summarize_directories
    errors.py            list_errors
    readonly_query.py     run_readonly_query, get_catalog_schema
    move.py               move
  tools/              small stateless helpers (hashing, mime detection, path resolution, entry queries)
tests/

Adding a tool group: create `mcp/<name>.py` with
`def register(mcp: FastMCP, catalog: Catalog) -> None:` that declares `@mcp.tool`
functions, then add `<name>.register` to `REGISTRARS`.

## Installation

pipx install rpg-librarian-mcp

Copy `.env.example` to `.env` in your library root and adjust as needed — see
"Running" below for how it's discovered.

### Database setup

The catalog's SQLite database (`<library root>/.catalog/catalog.db`) is
created automatically, migrated up to `head`, the first time the server runs
against a library that doesn't have one yet. No manual step needed for a
fresh install — `alembic.ini` and the migration scripts are bundled inside
the installed package, so this works the same whether you're running from a
source checkout or a `pipx`/PyPI install.

This only handles *creation*. If a future release adds a new migration, an
already-existing catalog is **not** auto-upgraded — bring it to `head`
yourself, from inside the library directory:

rpg-librarian-mcp --migrate

This works the same way regardless of install method (source checkout,
`pipx`, PyPI) since it locates the bundled migrations the same way the
auto-create path does. It's a safe no-op if the catalog is already at head,
and exits with a clear error (instead of starting the server) if there's no
catalog at this location yet.

## Running

rpg-librarian-mcp

Register with Claude Code:

claude mcp add rpg-librarian -- rpg-librarian-mcp

The library root is the working directory the server is launched from, and
the catalog is always `<library root>/.catalog` — neither is configurable.
Other config comes from the environment, with a `.env` found upward from
that directory loaded at startup. See `.env.example`.

## Development

Clone and install with dev dependencies:

git clone <repo-url>
cd rpg-librarian-mcp
uv sync

Run the server from a checkout with `uv run rpg-librarian-mcp`.

### Setting up your dev environment

Copy `.env.example` to `.env` at the repo root (or wherever you're running
`alembic` from) and set `DATABASE_URL` to point at the SQLite db you want
`alembic` commands to target, e.g. a test library's catalog:

DATABASE_URL=sqlite:////home/you/data/rpgtest/.catalog/catalog.db

`migrations/env.py` loads `.env` automatically (searching upward from wherever
you run `alembic` from) before reading `DATABASE_URL` — no need to `source`
or export it yourself. This is separate from the server itself, which always
resolves its db from the library root (cwd), never from this variable.

### Running or authoring a migration

`alembic.ini` lives inside the package (`src/rpg_librarian_mcp/alembic/`),
not at the repo root — it's bundled there so migrations work post-install
(PyPI/`pipx`), not just from a source checkout. Every `alembic` CLI
invocation needs `-c src/rpg_librarian_mcp/alembic/alembic.ini` explicitly;
bare `alembic ...` from the repo root won't find the config.

After changing a model in `model/`, generate a revision from the diff:

uv run alembic -c src/rpg_librarian_mcp/alembic/alembic.ini revision --autogenerate -m "..."

Review the generated file under
`src/rpg_librarian_mcp/alembic/migrations/versions/` — autogenerate can miss
renames (reads as drop+add) or defaults, so fix up by hand if needed. Then
apply it to your `DATABASE_URL` target to confirm it runs cleanly:

uv run alembic -c src/rpg_librarian_mcp/alembic/alembic.ini upgrade head

## Checks

uv run pytest
uv run ruff check --fix
uv run ruff format
uv run ty check

These also run as git hooks — ruff and ty on commit, pytest on push. Install
them once per clone:

uv run pre-commit install --install-hooks -t pre-commit -t pre-push

The hooks shell out to `uv run`, so tool versions come from the `dev`
dependency group in `pyproject.toml` — bump them there, not in
`.pre-commit-config.yaml`. When `ruff check --fix` or `ruff format` rewrites a
file, the commit fails and the fix is left unstaged; `git add` it and commit
again.
