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
  resources/
    CLAUDE.md          default CLAUDE.md seeded into a new library root
    llm_settings.yaml   checked-in litellm model choice, read via importlib.resources
    prompts/            bundled Jinja prompt templates (e.g. read_pdfs's LLM prompt)
  model/             SQLModel tables (Entry, Error, MediaType, PdfContents, ...)
  commands/          CommandProtocol + per-tool business logic (UpdateCatalogCommand, ...)
  llm/               litellm settings loader + PDF description/system judgment
  mcp/
    init.py      REGISTRARS list -- add new tool modules here
    status.py        librarian_status
    update_catalog.py
    directory_status.py  list_directory_entries, summarize_directories
    errors.py            list_errors
    readonly_query.py     run_readonly_query, get_catalog_schema
    move.py               move
    metadata.py           update_metadata
    read_pdfs.py          read_pdfs
  tools/              small stateless helpers (hashing, mime detection, path
                       resolution, entry queries, barcode scanning, PDF text
                       extraction, OCR)
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

The same first-time bootstrap also seeds a starter `CLAUDE.md` in the
library root, from a packaged default (`resources/CLAUDE.md`), if one isn't
already there. An existing `CLAUDE.md` is never overwritten, and this only
happens at the moment `.catalog` is first created — not on every run.

### `read_pdfs`: Tesseract OCR

`read_pdfs` OCRs scanned PDF pages via `pytesseract`, which wraps the
Tesseract OCR **system binary** — this is not installed by `pip`/`uv sync`,
you need it on `PATH` separately:

- Debian/Ubuntu: `sudo apt install tesseract-ocr`
- macOS (Homebrew): `brew install tesseract`
- Windows: install from the
  [Tesseract at UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
  builds and ensure `tesseract.exe` is on `PATH`.

If the binary is missing, `read_pdfs` fails immediately (before scanning any
files) with a clear error, rather than failing once per scanned PDF.

### `read_pdfs`: LLM provider credentials

`read_pdfs` also asks an LLM (via `litellm`) to summarize a PDF's
description and guess its RPG system from sampled page text. The **model
choice** is checked into the repo (`resources/llm_settings.yaml`), but the
**provider credentials** are not — set whichever API key your chosen model's
provider needs (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) in your `.env`,
following `litellm`'s own
[provider docs](https://docs.litellm.ai/docs/providers) for the exact
variable name. See `.env.example`.

### `search_rpg_geek` / `lookup_rpg_geek_product`: RPGGeek credentials

These call the [RPGGeek](https://rpggeek.com) XML API. Basic search/lookup
works unauthenticated — `RPGGEEK_BEARER_TOKEN` in your `.env` is optional,
only needed to raise RPGGeek's rate limits. See `.env.example`.

### `search_dtrpg`: DriveThruRPG credentials

This calls the DriveThruRPG vBeta API and **requires** `DTRPG_API_KEY` in
your `.env` — an application key from your DriveThruRPG account. Without
it, this tool fails with a clear error on first use; the rest of the
server is unaffected. See `.env.example`.

### `lookup_isbn`: Google Books credentials (optional)

`lookup_isbn` falls back Google Books → Open Library → Wikidata. It works
with no configuration — Open Library and Wikidata need no key — but
`GOOGLE_BOOKS_API_KEY` in your `.env` is recommended: it gets a much
higher quota than Google Books' anonymous access, and Google Books is the
only one of the three that returns a description in the same response.
See `.env.example`.

### Recommended companion: Open Library MCP server

[`openlibrary-mcp-server`](https://github.com/cyanheads/openlibrary-mcp-server)
gives the model direct access to the Open Library API — searching books and
authors, fetching editions, browsing subjects, and resolving cover images —
which is useful alongside `rpg-librarian-mcp` for identifying and enriching
cataloged products. It requires no API key.

Install and register it with Claude Code:

    claude mcp add openlibrary-mcp-server -- npx -y @cyanheads/openlibrary-mcp-server@latest

Or add it directly to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openlibrary-mcp-server": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@cyanheads/openlibrary-mcp-server@latest"]
    }
  }
}
```

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
or export it yourself. The server's own bootstrap path (`db.py`) explicitly
sets its target db to the library root's own `.catalog/catalog.db` before
running migrations, so it does not *intend* to read this variable at all --
but `env.py` unconditionally lets `DATABASE_URL` override whatever caller set,
if the variable happens to be set. In normal server use this is harmless: a
real library root elsewhere on disk won't have this repo's `.env` anywhere
above it, so `find_dotenv` never finds one to load. It only bites if you
invoke the server's bootstrap code (`ensure_bootstrapped`, `--migrate`) from
somewhere `.env`'s `DATABASE_URL` *is* discoverable upward from cwd -- e.g.
testing against a scratch library from within this checkout -- in which case
that stray value silently wins over the library root you meant to target.
Export `DATABASE_URL` yourself (real env vars aren't overridden by `.env`) if
you need to rule this out.

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
