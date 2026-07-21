# rpg-librarian-mcp

MCP server (stdio) for cataloging and organizing a digital RPG archive.

## Layout

```
src/rpg_librarian_mcp/
  __main__.py     entry point (`rpg-librarian-mcp` / `python -m rpg_librarian_mcp`)
  server.py       builds the FastMCP server, registers tools, runs stdio
  config.py       .env loading + Config (library root = cwd)
  tools/
    __init__.py   REGISTRARS list -- add new tool modules here
    status.py     librarian_status (template for new tool modules)
tests/
```

Adding a tool group: create `tools/<name>.py` with
`def register(mcp: FastMCP, config: Config) -> None:` that declares `@mcp.tool`
functions, then add `<name>.register` to `REGISTRARS`.

## Running

```
uv sync
uv run rpg-librarian-mcp
```

Register with Claude Code:

```
claude mcp add rpg-librarian -- uv --directory C:\proj\rpg-librarian-mcp run rpg-librarian-mcp
```

The library root is the working directory the server is launched from, and the
catalog is always `<library root>\.catalog` — neither is configurable. Other
config comes from the environment, with a `.env` found upward from that
directory loaded at startup. See `.env.example`.

## Checks

```
uv run pytest
uv run ruff check --fix
uv run ruff format
uv run ty check
```

These also run as git hooks — ruff and ty on commit, pytest on push. Install
them once per clone:

```
uv run pre-commit install --install-hooks -t pre-commit -t pre-push
```

The hooks shell out to `uv run`, so tool versions come from the `dev`
dependency group in `pyproject.toml` — bump them there, not in
`.pre-commit-config.yaml`. When `ruff check --fix` or `ruff format` rewrites a
file, the commit fails and the fix is left unstaged; `git add` it and commit
again.
