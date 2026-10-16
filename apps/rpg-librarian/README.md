# rpg-librarian

Turns unorganized dumps of RPG content on a network share into an organized library.
Runs as a CLI (`init`, `add-source`, `scan`, `quick-dedupe`, `clean`, `find-packs`,
`enrich`, `reorganize`) or
as a FastMCP stdio server (`serve`). The usual order is `scan`, `find-packs`, `enrich`,
then filing (the `process-batch` skill), then `reorganize`. See `.work-items/rpg-librarian-app-refactor/` for the design.

## Agent skills

RPG applications and utilities use `rpg-software`, with the software family or
publisher as the product line and the specific application or release as the
product. VTT content packs continue to use `vtt packs`.

Travel guidebooks use the `travel-guides` product type, with the publisher or guide
series as the product line (for example `Lonely Planet`) and the individual book as
the product (for example `Japan, 18th Edition`). Other guide publishers can have
their own lines under the same type. Re-run `rpg-librarian init --library <library>
--catalog <catalog.db>` to add missing seed types to an existing catalog.

`init` installs the bundled `process-batch`, `review-items`, and
`review-organization` skills into all three
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

Twenty-one tools: `list_unfiled` (the worklist), `list_product_types`, `list_product_lines`,
`report_entry`, `report_product`, `report_line`, `describe_schema`, `query` (read-only
SQL), `update_product`, `clear_errors` (clears every recorded error, or only some
stages' errors), `rename-file` (renames a cataloged file on disk and updates its
catalog path, or, for a kept file whose product has moved, only in the catalog for
`reorganize` to apply), and the pack tools `report-pack`, `create-pack`, `add-to-pack`,
and `remove-from-pack`, plus six `organization_review_*` tools described below.
The existing item tools use entry IDs: a file's or a pack's. Organization review also
explicitly exposes stable file IDs for membership changes and finding IDs for
recommendations. The filing operations are also available on the command line (`list-unfiled`,
`list-types`, `list-lines`, `report-entry`, `report-product`, `report-line`,
`update-product`, `clear-errors [--stage STAGE ...]`, `report-pack`, `create-pack`,
`add-to-pack`, `remove-from-pack`) and print JSON. Filing decisions move files when
you run `reorganize`; `quick-dedupe` finds and moves duplicate files immediately.

## Reviewing library organization

Invoke `$review-organization` (or ask to review the library's organization). The
invoking LLM compares related products, lines, and packs, applies well-supported
corrections automatically, and saves judgment calls for `$review-items`.

The MCP interface uses `organization_review_start`, `organization_review_group`,
`organization_review_commit`, `organization_review_receipt`,
`organization_review_findings`, and `organization_review_resolve`. A default pass
examines three product or unassigned-folder groups; a selected product line and
batch size can be requested. Interrupted passes resume from database records.
Unchanged groups stay examined; changed content, evidence, or relationships make
them eligible again. Coverage means examined, not guaranteed correct.

Each group's automatic correction and explanation commit atomically. Snapshot
fingerprints reject stale corrections. Findings are keyed to stable file IDs so
pack membership changes do not erase them. Organization recommendations appear in
the existing review queue and retain your explicit resolutions. Unchanged owner
choices cannot be automatically reopened; changed evidence needs an explanation.

Catalog migration `0007` adds `organization_coverage`, `organization_run`, and
`organization_finding`, without changing existing content or assignments. The MCP
server upgrades on startup; restart an existing server to load the new tools.
Re-run `init` to install a missing skill. For an existing customized review-items
copy, merge the new organization-recommendation instructions rather than erasing
customizations.

This skill changes catalog organization only. It does not scan, enrich, rename,
move, or delete files. Preview placement with `rpg-librarian reorganize --dry-run`,
then run `reorganize` when ready to make the physical library match the catalog.

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
`call_finished` line with the totals; they share a `call_id`.
Files needing processing also emit `file_started` and `file_stage_started` before
work begins. Each event is flushed immediately and includes `pid`; use
`file_event_id` to match start/stage markers to the final `file` event. After a hard
crash, the last unmatched start/stage identifies the active input and operation.
It is a candidate for investigation, not proof of corrupt content.

Python's fault handler automatically appends fatal-error stacks to
`logs/crash-stderr.log` for the application and its isolated extraction workers.
Activation headers include the PID and UTC time to correlate with `events.log`.
These diagnostics apply on the next process start; no special invocation is needed.
For startup failures and other native stderr messages, also launch with
`PYTHONFAULTHANDLER=1` and append stderr to that same file.

For example:

```bash
jq -c 'select(.event=="call_finished") | {command, outcome, seen, processed, errored}' logs/events.log
jq -c 'select(.event=="file" and .outcome=="error") | {path, source, error_message}' logs/events.log
```

## Brendan OneDrive importer

`import-run brendan` is a resumable manual job. It uses the OneDrive and Gmail
settings in the application's `.env`, including the separate MSAL token-cache
path. This checkout loads `.env` from the application source location, so the
command can run from another directory. Existing environment variables take
precedence. The catalog still needs an explicit path or `RPG_LIBRARIAN_CATALOG`.
The Microsoft public client needs delegated personal-account read access; the
importer makes no remote writes.

Register a dedicated folder **inside an existing staging root**, then run:

```bash
uv run rpg-librarian import-source add brendan --catalog /path/to/catalog.db --inbox /path/to/inbox/brendan
uv run rpg-librarian import-source doctor brendan --catalog /path/to/catalog.db
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db
uv run rpg-librarian import-status brendan --catalog /path/to/catalog.db
```

The first `import-run` can also register the source, using `--inbox` or, when
there is exactly one staging root, its `brendan/` subdirectory. It never registers
a nested catalog root. Keep the same catalog, source IDs and destination on later
runs. `import-source auth brendan` performs Microsoft device sign-in if the cached
account needs authorization again; ordinary runs never open a sign-in prompt.
`doctor` checks cached access, shared-folder delta, destination reachability and
Claude CLI presence. It does not send a test email or verify Claude login.

Each top-level source folder is a complete transfer group. Selecting a folder
queues **all eligible missing files in that folder and every subfolder**, across
all file types. Default run limits are 100 transfer attempts, 5 GiB reserved
transfer bytes, two hours, and 50 filing entries. A large folder can take several
runs. **No scanning, pack discovery, enrichment or filing of that group starts
until its transfers are complete.** Repeat the same command to continue. Already
selected folders take priority, then fresh folders, then the initial backlog.
Other completed folders can progress while an individual file retries.

Graph delta provides the current metadata inventory; the root `catalog.json`
adds optional title context. Discovery saves every page and resumes interrupted
cycles. It does not download the whole share. Matching uses local product-line
names/aliases, distinctive filenames, exact sizes and conservative renamed-PDF
fingerprints. A metadata match is an ownership assumption, not byte equality.
The matching local occurrence must pass a current size/mtime check. Uncertain
matches are copied without a review gate. Downloaded candidates receive SHA-256
checks against fresh local catalog occurrences. Source content changes create
new revisions; remote removals never delete local files.

Files are copied under `brendan/<source-relative-path>` and existing destination
files are never overwritten. Every underscore-prefixed folder and all its
descendants are excluded at every depth. Root catalogs/organizing reports and
`_index.md` are control files. An underscore-prefixed **file** is otherwise allowed.
Nested remote shortcuts are not followed. Original source paths, remote IDs,
content versions, ownership methods, hashes and local file IDs remain in the
private journal, including after normal catalog cleaning.

Once a group is complete, the app scans only its imported files, finds packs,
enriches selected entries, and uses the signed-in Claude CLI to file them through
an explicit MCP configuration. The server rejects writes outside the selected
entries and imported files; shell, rename and pack-edit tools are unavailable to
that session. Placement is restricted to the imported files. Synthetic `brendan/`
is removed from enrichment path clues. Uncertain filing creates a catalog review
flag and allows other entries to continue. Review flags are resolved with the
normal `report-entry` and `update-product` commands.

Useful manual controls:

```bash
# Metadata only: creates inventory/progress records but copies no RPG content.
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db --discover-only
# Work on one entire top-level folder, possibly across repeated runs.
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db --folder 'Product line'
# Change pacing; byte limits are integers in bytes.
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db --max-files 20 --max-bytes 1073741824
# Allow one first file larger than the byte limit, rather than leaving it queued.
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db --allow-oversized
# Copy only; keep completed groups ready for a later processing run.
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db --no-process
# Process completed local groups without Microsoft access or discovery.
uv run rpg-librarian import-run brendan --catalog /path/to/catalog.db --process-only
# Export all unresolved reviews, including ones previously emailed.
uv run rpg-librarian import-reviews brendan --catalog /path/to/catalog.db
# Resolve a source/transfer/processing issue after correcting it.
uv run rpg-librarian import-review resolve 'source:access' --catalog /path/to/catalog.db
```

Only unresolved **newly actionable** issues generate a digest. Unchanged issues
already emailed remain in the persistent report without repeated mail. Transient
item failures retry after 5 minutes, 30 minutes, then two hours; three failed
attempts become a review. Sign-in/access problems are actionable immediately.
`--no-email` retains notifications for a later run. Failed delivery retains the
outbox and stable Message-ID; SMTP acceptance followed by a process crash can
produce a duplicate digest on retry. Empty and successful runs send no email.

State is in `imports/brendan.sqlite3` beside the catalog, with private catalog
context, review export and filing manifests in the same directory. Back up this
journal along with the catalog and token cache; do not delete it between runs.
The journal uses logical catalog file references rather than foreign keys, so
provenance survives catalog cleanup. A host file lock rejects overlapping
importer jobs. SQLite is intended for a local catalog/state disk, not the SMB
content share. Status pending byte counts include files whose ownership has not
yet been checked, so they are an upper bound on remaining downloads.

Incomplete metadata cycles delay processing to protect the complete-folder rule;
an outage before any new metadata page arrives still permits saved completed
local groups to process. Provider calls already in flight can exceed the nominal
run deadline; new calls stop when the deadline is reached. Restart interrupted
transfers from the beginning. Source renames update current provenance while
already published files retain their original copied paths. Pack discovery uses
the group's imported file IDs, so a changed top-level name does not lose those
files from its work scope. Persistent errors/reviews remain inspectable even
when the overall bounded run returns zero; shared access or mail failures return
nonzero. No automatic trash cleaning occurs.

No timer is installed by these commands. Run the importer manually as often as
needed; nightly scheduling can be added after that manual rollout.
