# RPG Librarian

Catalog and organize a digital RPG library from PDFs, maps, tokens, audio, models,
and other files. The current application is `rpg-librarian`: a CLI for bulk
processing and a FastMCP stdio server for agent-assisted filing.

The SQLite catalog records files, hashes, metadata, identification evidence,
products, packs, filing decisions, errors, and review flags. Filesystem organization
is applied separately by `reorganize`.

## Repository layout

- [apps/rpg-librarian/](apps/rpg-librarian/): the application, catalog, CLI,
  MCP tools, migrations, and bundled agent skills.
- [packages/rpg-librarian-tools/](packages/rpg-librarian-tools/): stateless file,
  PDF, identifier, and external-service operations used by the application.
- `scripts/`: migration checks, pack migration, and a local batch-processing helper.
- [WORK-ITEMS.md](WORK-ITEMS.md): tracked project work.

The tools package accepts explicit inputs and credentials and does not own catalog
state. Application orchestration belongs in `apps/rpg-librarian`.

## Install from a checkout

Use Python 3.14 or newer and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --all-packages
cp .env.example .env
uv run rpg-librarian --help
```

For file-type detection, install the system `libmagic` library. OCR of scanned PDFs
requires the Tesseract executable on `PATH`; video metadata extraction requires
MediaInfo. These system dependencies are separate from the Python dependencies.

For example, on Debian or Ubuntu:

```bash
sudo apt install libmagic1 tesseract-ocr libmediainfo0v5
```

## Configure the catalog and services

Catalog path precedence is `--catalog PATH`, then `RPG_LIBRARIAN_CATALOG`, then
`./catalog.db`. The library location is registered by `init --library PATH`;
it does not depend on the server's working directory.

The application loads `.env` using python-dotenv's upward discovery, and existing
environment variables win. In a source checkout, put `.env` at the repository root.
For scheduled or installed deployments, exporting the required variables avoids
depending on where dotenv discovery starts.

See [.env.example](.env.example) for:

- `RPG_LIBRARIAN_CATALOG`: the catalog database path.
- `DTRPG_API_KEY`: DriveThruRPG enrichment.
- `RPGGEEK_BEARER_TOKEN`: RPGGeek enrichment through the BoardGameGeek XML API.
- `SERPER_API_KEY`: Google search evidence through Serper.dev.
- `GOOGLE_BOOKS_API_KEY`: optional Google Books lookup before Open Library/Wikidata.
- `RPG_LIBRARIAN_LLM_MODEL`: LiteLLM model for text analysis and pack discovery
  (current default: `gpt-5.6-luna`), with the corresponding provider credentials.

Missing keys skip the relevant credential-dependent enrichment sources. Pack
discovery and nonempty text analysis need a working model/provider configuration.
Basic catalog creation, scanning, filing tools, and placement do not require an LLM.

## Initialize and process content

Create the library and inbox directories first. Registered roots must be separate:
an inbox cannot be inside a registered library root, and roots cannot overlap.
Keep the catalog outside content roots when practical.

From the repository checkout, substituting your actual paths:

```bash
export RPG_LIBRARIAN_CATALOG=/path/to/catalog.db

uv run rpg-librarian init --library /path/to/library
uv run rpg-librarian add-source /path/to/inbox --label inbox
uv run rpg-librarian scan --root /path/to/inbox
uv run rpg-librarian find-packs --root /path/to/inbox
uv run rpg-librarian enrich
```

`init` creates/migrates the catalog, seeds product types, registers the library,
and installs the bundled `process-batch`, `review-items`, and `review-organization` skills into the
library's `.claude/skills/`, `.codex/skills/`, and `.gemini/skills/` directories.
Existing local skill copies are preserved.

`scan` hashes and extracts metadata/text, skips unchanged files, records individual
errors, and recognizes exact duplicates and moved files. `find-packs` identifies
collective products such as map/token sets. `enrich` gathers cached identification
evidence; it operates across the catalog, not just the last scanned root.

Use `review-organization` to audit existing product, line, and pack relationships:
clear-cut catalog corrections apply automatically, judgment calls go to
`review-items`, and database-backed coverage resumes across invocations. Physical
moves remain the separate `reorganize` command. See the
[organization review workflow](apps/rpg-librarian/README.md#reviewing-library-organization).

Next, use the `process-batch` skill with the MCP tools to judge and file the
unfiled entries. It works by folder and uses filenames, folder context, extracted
metadata, and evidence. Uncertain filing can be deferred with a review flag.
Then preview and apply placement:

```bash
uv run rpg-librarian reorganize --dry-run
uv run rpg-librarian reorganize
```

Kept content is placed under `<library>/<type>/<line>/[<product>/]<file>`, with
product subfolders preserved where applicable. Duplicates, superseded content,
and discarded content go under `<library>/.trash/`. Placement refuses overwrites
and files changed since scanning.

The [application README](apps/rpg-librarian/README.md) documents packs, product types,
filename policy, detailed processing behavior, and review tools.
For the unattended pipeline, use:

```sh
rpg-librarian process-batch --catalog /path/to/catalog.db --root /path/to/inbox
```

The input must be a registered staging root. Scanning and pack discovery are scoped
to it; enrichment, filing and reorganization cover the catalog. The command writes
a local run summary and selectively emails the total review backlog instead of
opening interactive review. Rerunning preserves committed work. Claude CLI and the
existing SMTP settings are used; see the [batch documentation](apps/rpg-librarian/README.md#unattended-batch-processing)
for email suppression, recovery, counters, and exit behavior.

Live terminal output shows stage counts, current activity and elapsed time, with
periodic plain-text status when redirected. Stage results and review/email status
remain visible at completion; detailed private logs stay beside the run summary.

`scripts/process-batch.zsh` forwards to this command with `/phinneas/rpg/inbox` as
its default root. Interactive `/review-items` remains available separately.

## Run the MCP server

For a client that launches stdio MCP servers:

```bash
uv run --project /absolute/path/to/this/repo \
  rpg-librarian serve --catalog /absolute/path/to/catalog.db
```

Example client configuration:

```json
{
  "mcpServers": {
    "rpg-librarian": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/this/repo",
        "rpg-librarian",
        "serve",
        "--catalog",
        "/absolute/path/to/catalog.db"
      ]
    }
  }
}
```

Tools include the unfiled worklist, product type/line lookups, entry/product/pack
reports, read-only SQL, filing decisions, review flags, error clearing, pack
membership, and file renaming. Filing and reporting operations also have CLI
commands; see `uv run rpg-librarian --help`.

## Sync download sources

Register named OneDrive folders, then download and process each source serially:

```bash
rpg-librarian sync-source list --catalog /path/to/catalog.db
rpg-librarian sync-sources --catalog /path/to/catalog.db --inbox /path/to/inbox
# Select one source, or change the per-source automatic admission limit:
rpg-librarian sync-sources --catalog /path/to/catalog.db --inbox /path/to/inbox --source brendan --max-new-files 100
```

New and updated files already owned by matching SHA-256 are excluded before counting.
Zero pending files exit quietly; more than the per-source limit sends a manual-import
notice without publishing or processing that source. Small batches are copied safely,
then passed through the shared `process-batch` pipeline before the next source starts.
Failures do not stop other sources; one combined failure email is sent at the end.
Unfinished admitted batches resume automatically. Existing Brendan registrations and
history are adopted; `import-run` is retired with migration guidance.

OneDrive discovery tracks changes incrementally. Verified ownership links let
unchanged nightly runs check the known local copies without rebuilding the inbox
inventory or rereading contents. Full ownership matching runs weekly, or on demand
with `--full-reconcile`; changed or missing copies are rechecked immediately.

See [source registration, accounts and recovery](apps/rpg-librarian/README.md#sync-download-sources)
for setup, hash verification costs, notification rules and nightly scheduling examples.
OneDrive is the first provider adapter; Google Drive and Dropbox are not implemented.
No schedule is installed automatically.

## Cleanup and maintenance

For a fresh, uncataloged inbox containing many known exact copies, optionally run
`quick-dedupe --root PATH --dry-run`, then `quick-dedupe --root PATH` before scanning.
It moves confirmed duplicates to trash without extracting survivors. It refuses
an inbox containing ordinary cataloged files; use normal scanning for those.

`clean --dry-run` previews removal of duplicate, superseded, and discarded trash.
`clean` permanently deletes that trash and compacts SQLite. It also removes the
corresponding catalog records and hashes. See the application README before using it.

`sanitize-filenames` previews filename cleanup; `--apply` performs it with a
catalog backup and a durable rename journal.

Normal catalog sessions migrate an existing database to the current schema;
`init` creates a new one. There is no separate `--migrate` server option.
For migration development, the bundled Alembic configuration is at
`apps/rpg-librarian/src/rpg_librarian/alembic/alembic.ini`.
`DATABASE_URL` supplies the target for a direct Alembic invocation; application
commands use their explicit catalog path instead.

Runs append structured JSON events to `logs/events.log` beside the catalog,
with call identifiers, item outcomes, and run totals.

## Development checks

```bash
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
uv run python scripts/check_migrations.py
```

The migration check builds a temporary catalog and compares migrated schema with
the application's SQLModel metadata. The remaining existing tests cover the tools
package; application behavior can be checked directly with a scratch catalog.
Follow [.work-items/workflow.md](.work-items/workflow.md) for the
project's verification policy.

Install the repository hooks with:

```bash
uv run pre-commit install --install-hooks -t pre-commit -t pre-push
```
