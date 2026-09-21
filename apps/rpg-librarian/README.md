# rpg-librarian

Turns unorganized dumps of RPG content on a network share into an organized library.
Runs as a CLI (`init`, `add-source`, `scan`, `enrich`, `reorganize`) or as a FastMCP
stdio server (`serve`). See `.work-items/rpg-librarian-app-refactor/` for the design.

## Using the MCP server

`rpg-librarian serve` runs the tools on stdio. With Claude Code, from anywhere:

```bash
claude mcp add rpg-librarian-app -- uv run --project /path/to/this/repo \
  rpg-librarian serve --catalog /path/to/catalog.db
```

Nine tools: `list_unfiled` (the worklist), `list_product_types`, `list_product_lines`,
`report_file`, `report_product`, `report_line`, `describe_schema`, `query` (read-only
SQL), and `update_product` (the only writer). The same operations are available on the
command line (`list-unfiled`, `list-types`, `list-lines`, `report-file`, `report-product`,
`report-line`, `update-product`) and print JSON. Nothing moves on the share until you run
`reorganize`.

## Logs

Every run appends JSON lines to `logs/events.log`, beside the catalog. A `scan` or
`enrich` run is a `call_started` line, one `file` line per file (with its outcome), and a
`call_finished` line with the totals; they share a `call_id`. For example:

```bash
jq -c 'select(.event=="call_finished") | {command, outcome, seen, processed, errored}' logs/events.log
jq -c 'select(.event=="file" and .outcome=="error") | {path, source, error_message}' logs/events.log
```
