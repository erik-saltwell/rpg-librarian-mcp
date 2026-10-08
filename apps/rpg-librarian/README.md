# rpg-librarian

Turns unorganized dumps of RPG content on a network share into an organized library.
Runs as a CLI (`init`, `add-source`, `scan`, `quick-dedupe`, `clean`, `find-packs`,
`enrich`, `reorganize`) or
as a FastMCP stdio server (`serve`). The usual order is `scan`, `find-packs`, `enrich`,
then filing (the `process-batch` skill), then `reorganize`. See `.work-items/rpg-librarian-app-refactor/` for the design.

## Agent skills

`init` installs the bundled `process-batch` and `review-items` skills into all three
project-local agent locations: `.claude/skills/`, `.codex/skills/`, and
`.gemini/skills/`. Existing local copies are never overwritten, so they may be
customized safely. That also means a library initialized before an update keeps its old
skill copies: delete them and re-run `init` to pick up new guidance (for example the
pack instructions).

## Using the MCP server

`rpg-librarian serve` runs the tools on stdio. With Claude Code, from anywhere:

```bash
claude mcp add rpg-librarian-app -- uv run --project /path/to/this/repo \
  rpg-librarian serve --catalog /path/to/catalog.db
```

Fifteen tools: `list_unfiled` (the worklist), `list_product_types`, `list_product_lines`,
`report_entry`, `report_product`, `report_line`, `describe_schema`, `query` (read-only
SQL), `update_product`, `clear_errors` (clears every recorded error, or only some
stages' errors), `rename-file` (renames a cataloged file on disk and updates its
catalog path, or, for a kept file whose product has moved, only in the catalog for
`reorganize` to apply), and the pack tools `report-pack`, `create-pack`, `add-to-pack`,
and `remove-from-pack`. Every id they take or return is an entry id: a file's or a
pack's. The filing operations are also available on the command line (`list-unfiled`,
`list-types`, `list-lines`, `report-entry`, `report-product`, `report-line`,
`update-product`, `clear-errors [--stage STAGE ...]`, `report-pack`, `create-pack`,
`add-to-pack`, `remove-from-pack`) and print JSON. Filing decisions move files when
you run `reorganize`; `quick-dedupe` finds and moves duplicate files immediately.

## Quickly cleaning a large incoming dump

Use `quick-dedupe` before normal scanning when most incoming files are exact copies
of content already known to the catalog:

```bash
rpg-librarian add-source /phinneas/rpg/inbox
rpg-librarian quick-dedupe --root /phinneas/rpg/inbox --dry-run
rpg-librarian quick-dedupe --root /phinneas/rpg/inbox
```

Use the usual `--catalog PATH` option if needed. `--root` is required and must be a
registered staging root. The command refuses an inbox containing cataloged files
other than pending duplicates from earlier cleanup runs. It leaves every survivor
uncataloged, so moving the remaining files into an unregistered
`/phinneas/rpg/holding-pen` creates no dangling catalog references. Preserve folders,
then move complete folders back into inbox in manageable batches and run
`scripts/process-batch.zsh`. Moving the survivors out empties inbox; copying alone
leaves them there.

The command filters candidates by size and streams SHA-256 directly from the share.
It does no metadata/text extraction, OCR, enrichment, or pack discovery. It matches
present cataloged content (including cataloged trash) whose recorded size and
modified time still match, and also retains one copy of new content repeated within
the inbox. Existing pack members and library copies take precedence. Originals
are not rehashed; bring the existing catalog up to date before importing a dump.
`scripts/process-batch.zsh` runs quick cleanup first, then its usual full processing
sequence. If preliminary cleanup fails or refuses an already-cataloged inbox, it
prints a message and continues with normal scan. Duplicate-heavy fresh batches
avoid extraction work; mostly unique batches can take longer because survivors may
be hashed by both commands.
As with normal scan, dotfiles, hidden directory trees and agent instruction files
are excluded. Directory symlinks are not followed; file symlinks and nonregular
files are reported as errors. Empty directories are left in place.

Only confirmed duplicate occurrences get file/entry rows. They go immediately to
`<library>/.trash/duplicates/<source-id>-<source-name>/<original-relative-path>`
using the same filename allocation, non-overwriting movement, verified copying
across filesystems, and catalog bookkeeping as `reorganize`. Unrelated filing
decisions and errors are left alone. Keeping inbox and library on the same filesystem
allows cheap renames; across filesystems the duplicates must be copied and verified.

An extra inbox copy whose original is still uncataloged has a null
`duplicate_of_id`. Such unlinked duplicate rows are excluded from quick cleanup's
known originals, so rerunning does not consume the retained inbox survivor. When
normal scan later catalogs that survivor, it wins over these unlinked trash copies
and supplies their original id. Other cataloged trash participates normally.

`--dry-run` hashes and prints proposed moves without changing the catalog or files.
The final summary reports files seen/hashed, bytes hashed, duplicates, survivors,
moves, and errors. Errors return a nonzero exit status: resolve them and rerun before
moving the remaining inbox files into holding-pen. Failed moves leave cataloged
duplicate rows at their source, retryable by this command or `reorganize`. A survivor
without a catalog row will be hashed again on a later cleanup run if its size still
has potential matches.

## Emptying trash and reclaiming space

```bash
rpg-librarian clean --dry-run
rpg-librarian clean
```

Add `--catalog PATH` if needed. `clean` permanently deletes contents of the library's
`.trash/duplicates/`, `.trash/superseded/`, and `.trash/discarded/` buckets, including
uncataloged and hidden files. It removes their file/entry records, dependent metadata,
evidence, errors and review flags. Packs are removed when their last member is gone,
along with their entry/evidence and linked folder judgments. Catalog records for trash
files already removed by hand are cleaned too. Empty bucket directories are removed;
the library root and `.trash` root remain.

Other library files, staging roots, unknown trash buckets, products and product lines
are retained. Files and pack members marked keep but still sitting in trash are
blocked: run `reorganize` to move them out before cleaning. Symbolic links inside
trash are unlinked without following their targets; symlinked trash/bucket roots are
refused. File changes during enumeration are reported rather than deleted.

Surviving automatic duplicates whose original is removed become unfiled, have their
original reference cleared, and are scheduled for full rescanning. This prevents
a later `reorganize` from trashing the last remaining copy, including hash-only files
created by `quick-dedupe`. Explicit filing decisions on surviving files are retained.

Successful deletions are committed to the catalog in batches. Failed file deletions
leave their rows intact and return a nonzero exit status. If a catalog write fails
after files have been deleted, rerun `clean` to remove the now-absent trash records.
Committed filesystem deletions cannot be undone. `--dry-run` only previews cleanup;
it deletes nothing and does not compact the database.

After cleanup, SQLite `VACUUM` compacts the catalog to reclaim unused database pages.
The summary reports deleted bytes/files, removed records/packs, released duplicates,
errors, and catalog size before/after compaction. A compaction failure also returns
nonzero; the completed cleanup remains committed and `clean` can be rerun. Compaction
needs temporary disk space to rewrite SQLite and can be blocked by active database
operations.

Cleaning forgets the removed content's hashes and decisions. Unlike keeping cataloged
trash, it will not suppress the same discarded file if it appears in a future dump.

## Packs

A pack is a set of files with one collective identity and none of their own: a map
pack, a token set, an audio or STL set. It is one catalog entry (`entry.type = 'pack'`);
its member files have no entry of their own (`file.pack_id`). The pack holds the
disposition and its entry the product, and both apply to every member. A product holds
at most one kept pack. Members of a kept pack are placed under the product folder with
the pack's folder structure kept (`Day/Night/`, `Gridded/Gridless/`); a pack's failed
moves are summarized in one `reorganize` error on its entry.

`find-packs` finds them. It reads the catalog only (no share walk) and walks each root's
folders top-down. A folder is asked about only if it has unfiled files and passes the
gate (at least 3 files, at least 80% of them not documents). Sibling folders go to the
model in one call each (`RPG_LIBRARIAN_LLM_MODEL`, as for text analysis), with their
evidence: file counts and media types, numbered name runs, variant subfolders, and one
cached Google search per folder name (none for generic names such as "Maps"). The
model answers `pack`, `container` (descend), or `no_packs`. A pack is formed only if no
existing decision is lost (its files all unfiled, or all filed alike); otherwise the
folder is recorded as `mixed` and left as loose files. Every answer is stored in
`folder_judgment` with a fingerprint and reused while the folder is unchanged, and a
pack is never re-judged. `--dry-run` asks and stores answers but forms nothing (a later
run forms them without asking again); `--limit N` caps model calls; `--no-search`
skips searches; `--root PATH` limits the walk.

`scan` keeps members in their pack when they change. A new file arriving below a
pack's folder joins it; a member that fails a scan stage is taken out of its pack (it
gets its own entry and the error). Correct packs with `create-pack FOLDER`,
`add-to-pack ENTRY PATH`, and `remove-from-pack ENTRY PATH`, where `PATH` is a file or
folder relative to its root.

`enrich` looks each PDF up on its own, and each pack once: DriveThruRPG and RPGGeek by
its folder name, its parent folder's name, both combined, then its member PDFs' titles;
Google by its folder names (unless `find-packs` already stored that search); text
analysis from its members' pooled text samples, documents first. ISBN lookup never
runs for packs. For loose non-PDF files (maps, tokens, art, audio) outside packs, only
Google searches, once per folder group (the first three folders below the root) rather
than once per file.

`scan` samples files classified as text from its temporary local copy, reading at
most 64 KiB. It decodes UTF-8, removes an optional BOM, and replaces undecodable bytes
with U+FFFD (`�`), including partial characters at the read boundary. The sample is
also capped at 64 KiB of UTF-8 text, dropping any final character split by that cap.
It is stored against the source file in `file_text.sample_pages` as `{"1": "..."}`:
one logical page, alongside the existing physical-page samples for PDFs. Text files
have no extracted barcode, ISBN, or ISSN. `enrich --source text_analysis` consumes
these samples; empty samples are recorded as considered without calling the model.
Empty-file MIME types use the existing extension fallback, so zero-byte `.txt`
files also receive an empty sample.
Already cataloged, unchanged text files need `scan --force` to populate their samples.

`reorganize --dry-run` previews the moves, and `reorganize` performs them: filed products go to
`library/<type>/<line>/[<product>/]<file>`, and duplicates, superseded, and discarded files
to `library/.trash/<bucket>/`. Below the product folder, a product keeps the subfolders
under the deepest folder its files share in the source (such as `Day/` and `Night/` map
variants). Each kept file's path below its product folder is stored in the catalog
(`file.subpath`) when its product first moves, so later runs never reshuffle it; it
changes when the file is re-filed, renamed with `rename-file`, or its filename needs
cleanup or a collision suffix. It never
overwrites, refuses files that changed since the last `scan`, and removes only folders
it emptied. Try it on a copy first.

Library filenames preserve Unicode letters/numbers (and combining accents), ordinary
spaces, and `- _ . & $ # @ % ^ ( ) [ ]`. Other characters become dashes. Trailing
spaces/dots are removed and reserved Windows device names are prefixed with `_`.
Extensions are preserved; long stems are shortened to fit a 200-byte/UTF-16-unit
component limit. Collision comparisons ignore case. Existing compliant names keep
their place; remaining files receive ` (2)`, ` (3)`, etc. before the extension in
file-ID order. Pack members and trash files follow the same policy. Staging source
names stay unchanged until placement into the library.

To clean existing library filenames without reorganizing their folders or assignments:

```bash
rpg-librarian sanitize-filenames --catalog /path/to/catalog.db --out preview.json
rpg-librarian sanitize-filenames --catalog /path/to/catalog.db --apply --out applied.json
```

Preview is the default; `--dry-run` is also accepted. Apply refuses blocked sources,
backs up SQLite under `backups/` beside the catalog, and writes a durable JSONL journal
with old/new paths and per-file completion records. Each rename refuses overwrites
and updates the catalog in a transaction; a failed catalog write rolls the rename
back. A second run changes nothing once cleanup is complete. The database backup
alone does not undo disk renames: use the matching journal if recovery is required.

## Logs

Every run appends JSON lines to `logs/events.log`, beside the catalog. A `scan` or
`enrich` run is a `call_started` line, one `file` line per file (with its outcome), and a
`call_finished` line with the totals; they share a `call_id`. For example:

```bash
jq -c 'select(.event=="call_finished") | {command, outcome, seen, processed, errored}' logs/events.log
jq -c 'select(.event=="file" and .outcome=="error") | {path, source, error_message}' logs/events.log
```
