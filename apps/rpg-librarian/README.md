# rpg-librarian

Turns unorganized dumps of RPG content on a network share into an organized library.
Runs as a CLI (`init`, `add-source`, `scan`, `enrich`, `reorganize`) or as a FastMCP
stdio server (`serve`). See `.work-items/rpg-librarian-app-refactor/` for the design.

## Agent skills

`init` installs the bundled `process-batch` and `review-items` skills into all three
project-local agent locations: `.claude/skills/`, `.codex/skills/`, and
`.gemini/skills/`. Existing local copies are never overwritten, so they may be
customized safely.

## Using the MCP server

`rpg-librarian serve` runs the tools on stdio. With Claude Code, from anywhere:

```bash
claude mcp add rpg-librarian-app -- uv run --project /path/to/this/repo \
  rpg-librarian serve --catalog /path/to/catalog.db
```

Ten tools: `list_unfiled` (the worklist), `list_product_types`, `list_product_lines`,
`report_file`, `report_product`, `report_line`, `describe_schema`, `query` (read-only
SQL), `update_product`, and `rename-file` (renames a cataloged file on disk and updates
its catalog path, or, for a kept file whose product has moved, only in the catalog for
`reorganize` to apply). The filing operations are also available on the
command line (`list-unfiled`, `list-types`, `list-lines`, `report-file`, `report-product`,
`report-line`, `update-product`) and print JSON. Nothing moves on the share until you run
`reorganize`.

`enrich` looks each PDF up on its own. Only Google searches for other files (maps,
tokens, art, audio), and it searches once per pack (the first three folders below the
root) rather than once per file: every file in the pack shares that query and its hits.

`reorganize --dry-run` previews the moves, and `reorganize` performs them: filed products go to
`library/<type>/<line>/[<product>/]<file>`, and duplicates, superseded, and discarded files
to `library/.trash/<bucket>/`. Below the product folder, a product keeps the subfolders
under the deepest folder its files share in the source (such as `Day/` and `Night/` map
variants). Each kept file's path below its product folder is stored in the catalog
(`file.subpath`) when its product first moves, so later runs never reshuffle it; it
changes only when the file is re-filed or renamed with `rename-file`. It never
overwrites, refuses files that changed since the last `scan`, and removes only folders
it emptied. Try it on a copy first.

## Logs

Every run appends JSON lines to `logs/events.log`, beside the catalog. A `scan` or
`enrich` run is a `call_started` line, one `file` line per file (with its outcome), and a
`call_finished` line with the totals; they share a `call_id`. For example:

```bash
jq -c 'select(.event=="call_finished") | {command, outcome, seen, processed, errored}' logs/events.log
jq -c 'select(.event=="file" and .outcome=="error") | {path, source, error_message}' logs/events.log
```
