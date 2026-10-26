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

## Visual inspection

The MCP `view_file` tool returns an image for the agent's own vision capabilities,
with source and dimension metadata. Use `entry_id` for a loose image, PDF or Illustrator (.ai) file; PDF/AI
`page` numbers start at 1 and default to the first page. For a pack, additionally
select `member_path` using a member's root-relative `relative_path` and `root_id`
from `report-pack`. It resolves the current catalog location, never arbitrary paths.

Illustrator files render their saved PDF artwork with MuPDF, or legacy PostScript
artwork with Ghostscript (`gs` on PATH; Debian/Ubuntu package `ghostscript`). This
also works with older/generic catalog classifications. Select a page with `page`;
PostScript page counts are reported as unknown (`null`). Rendering does not expose
editable layers or hidden objects. Native-only AI content still requires re-saving
with **Create PDF Compatible File** or exporting a PDF/image.

Ghostscript runs with `-dSAFER`, no interactive input, bounded preview dimensions,
private temporary output and a 40-second subprocess timeout inside the existing
60-second disposable worker. Missing Ghostscript, invalid bounding boxes, missing
pages and rendering failures return tool errors. Source files remain unchanged.

One preview is returned per call: JPEG, default longest edge 1600 pixels,
`max_edge` from 512 to 2400. Images use the first frame, EXIF orientation and white
behind transparency. Rendering runs in a disposable worker with a 60-second limit;
inputs are limited to 512 MiB, decoded images to 40 megapixels, and output to 8 MiB.
Missing, unsupported, encrypted, damaged or oversized inputs return tool errors.
No catalog judgments or source files are changed. Clients must pass MCP image
content to a vision-capable model; verify that integration before unattended use.

The bundled process-batch and review-items skills instruct agents to inspect visual
questions before requesting human inspection, while retaining uncertainty about
exact product identities and editions when evidence remains insufficient.

## Unattended batch processing

```sh
rpg-librarian process-batch --catalog /path/to/catalog.db --root /path/to/inbox
```

`--root` must name a registered, reachable staging root (use `add-source` first).
It does not accept a descendant folder or silently process its parent. The command
runs quick deduplication, scan, pack discovery, enrichment, agent filing, and
reorganization. Deduplication, scan and discovery are limited to this root;
enrichment, filing and reorganization cover the entire catalog. The command makes
catalog decisions and moves files, as the previous shell script did.

Claude CLI must be installed and signed in. The command supplies the bundled filing
instructions and an explicit catalog-bound MCP configuration, so it can run from
another working directory without a local slash-command copy or MCP configuration.
Filing includes visual inspection and pack tools; arbitrary shell tools and physical
renaming are not available to the agent. Uncertain judgments become review flags.
It does not open an interactive review session. Review later with `/review-items`.

The terminal shows a live stage display with elapsed time, counts and the current
file, folder, lookup source or agent tool. Scan and dedupe name the input before
working on it. Enrichment counts entries or shared queries as appropriate; pack
search/model activity and catalog filing progress are shown separately. Reorganization
shows placement planning and current moves. Known totals get a progress bar; work
with a dynamically discovered total uses activity counts without a guessed percentage.

A slow operation keeps the elapsed clock visible and shows how long it has been
since the last reported progress. This is a wait indication, not proof of a stall.
When stderr is redirected or the terminal is dumb, status is printed at phase
changes and at least every 15 seconds while a stage is running, without ANSI cursor
controls. A few affected file paths are shown for recoverable errors; further issues
stay in the detailed logs. Every stage leaves outcome/counts, and the final summary
shows stage results, total review backlog and email status/reason.

Progress is separate from private child stdout/stderr and the agent's JSON result.
Stage snapshots are retained as `<stage>-progress.json` beside the run summary;
filing's optional activity snapshot contains tool names/status only, never arguments
or model/document content. Existing running parent processes keep their old display;
new invocations pick up the improved output without changing the command.

Each invocation prints a private local summary path under
`logs/process-batch/<run-id>/summary.json` beside the catalog. It includes stage
outcomes/counters, new-input observations, total/category review counts, and email
status or suppression reason. Stage stdout/stderr and private agent output live
beside the summary. Records are retained until you remove them. Do not publish raw
agent output: it can contain document evidence. Fatal stacks also appear in the
existing `logs/crash-stderr.log`.

Email uses the same `RPG_LIBRARIAN_SMTP_USERNAME`, `SMTP_PASSWORD`, `REVIEW_EMAIL_TO`,
`SMTP_HOST`, `SMTP_PORT` and `SMTP_TLS` settings as the Brendan importer (all names
have the `RPG_LIBRARIAN_` prefix). TLS is required, using `ssl` or `starttls`.

- No email when there is no new or changed input, even with older reviews or later
  processing errors. Unchanged extraction retries alone are not new input.
- No email when all processing completes without issues and the review backlog is
  empty.
- Otherwise, email the run outcome, stages, total backlog and category counts.
  Counts include older unresolved reviews across the entire catalog, not just this
  root or run. Input is observed before deduplication can move new duplicates away.
- If input enumeration fails before its count is known, the count stays unknown
  and a failure email is attempted. Unavailable backlog counts are also unknown,
  never silently zero. A failed delivery remains visible in the summary.

Notification receipts retain sender, recipient, subject, Message-ID and, after
successful SMTP submission, `smtp_accepted_at`. Status `sent` means SMTP accepted
the message; it does not confirm Inbox placement. Search All Mail by subject or
Message-ID and check filters or other clients for archive rules if mail is missing.
Filing sends its private mode-0600 `filing-prompt.txt` through stdin. Agent errors
are in `filing-agent-stderr.log`; worker exceptions remain in `filing-stderr.log`.

`review_backlog` is the shared MCP definition of outstanding review work. It covers
flags, blocked moves, unresolved folder judgments and deferred organization
findings. Entry flags and blocked moves count once in the total, but both category
counts include that entry. Marker-only flags linked to deferred findings count with
the finding; unrelated flag questions remain separate. Folders and findings are
separate review identities, so this total is review items, not a count of files or
conflict-resolution actions. Follow `next_after_key` when MCP results are truncated.

Rerun the same command after a failure. Committed scan/evidence/filing decisions and
completed moves are retained; eligibility is recomputed from the catalog rather
than replaying old stage results. Outstanding catalog-wide work still runs when
there is no new input; email eligibility is evaluated for the current invocation.
Quick-deduplication failure is recorded and processing continues. A fatal later
stage stops dependent stages, then the parent attempts final reporting. Handled
file errors, incomplete agent filing and source failures are recorded even when
an existing standalone command would return zero.

The exit code is zero for complete processing with any required email accepted;
a review backlog alone is not a failure. Processing issues, incomplete stages and
email failures return nonzero; interrupts retain conventional interrupt codes.
Batch runs and Brendan imports share a cooperative per-catalog lock. Ordinary
standalone commands and interactive MCP writers are not covered by that lock.

Processing stages run in child processes so a stage segfault can be recorded by
the parent. If the parent or machine is killed, its last atomic stage record remains
available; the next batch marks abandoned runs interrupted and stops children with
that run's ownership token before proceeding. This provides recovery, not immediate
notification after a machine failure. An SMTP acceptance followed by a parent crash
can leave delivery uncertain; old notifications are not automatically replayed.

The repository and production `process-batch.zsh` wrappers forward to this command,
retaining `/phinneas/rpg/inbox` as the default root. The production wrapper also
anchors `catalog.db` beside the script, independent of the calling directory. Pass
CLI flags to override these defaults.

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

## Sync download sources

`sync-sources` is a one-shot nightly coordinator. It processes registered sources
**serially**: discover, classify, admit, copy and finish `process-batch` for one source
before attempting the next. Discovery/download failures and processing failures are
recorded per source; other sources continue. Any failure returns nonzero and sends
one combined failure email after all selected sources have been attempted.

### Registry and accounts

The catalog needs a reachable library and a registered staging inbox (`add-source`).
Download sources are separate named remote folders. A source has a stable lowercase
name, provider, account profile, remote folder identity and enabled flag. Source
names form local inbox namespaces; they are not product lines. Multiple folders can
share an authenticated account. OneDrive is implemented; the provider boundary owns
observation, version validation and downloading so future adapters can reuse the
same admission, copy, recovery and processing logic.

```bash
# First folder on an account; IDs/cache defaults may come from the existing .env.
rpg-librarian sync-source add brendan --catalog /path/to/catalog.db \
  --provider onedrive --account personal \
  --drive-id DRIVE_ID --folder-id ROOT_ITEM_ID \
  --client-id MICROSOFT_PUBLIC_CLIENT_ID --token-cache /private/path/msal.json
# Another folder on the same account:
rpg-librarian sync-source add other-folder --catalog /path/to/catalog.db \
  --account personal --drive-id DRIVE_ID --folder-id OTHER_ITEM_ID
rpg-librarian sync-source auth brendan --catalog /path/to/catalog.db
rpg-librarian sync-source doctor brendan --catalog /path/to/catalog.db
rpg-librarian sync-source list --catalog /path/to/catalog.db
rpg-librarian sync-source status brendan --catalog /path/to/catalog.db
rpg-librarian sync-source disable other-folder --catalog /path/to/catalog.db
rpg-librarian sync-source enable other-folder --catalog /path/to/catalog.db
```

`--authority` and `--scopes` configure a new account profile when needed. Auth is an
explicit interactive Microsoft sign-in; nightly runs use the private token cache
and never prompt. `doctor` checks source access and saves metadata observation,
without copying, running an agent, or sending email. The application loads its
existing `.env`; inherited environment variables take precedence. No token contents
or signed download URLs are stored in source definitions or notifications.

### Running and admission

```bash
rpg-librarian sync-sources --catalog /path/to/catalog.db --inbox /path/to/inbox
rpg-librarian sync-sources --catalog /path/to/catalog.db --inbox /path/to/inbox \
  --source brendan --max-new-files 100
```

All enabled sources run in name order by default. Repeated `--source` options select
an explicit order, including disabled sources for an intentional manual run. Names
are attempted once per invocation. `--inbox` names the exact registered staging
root; files are placed under `<inbox>/<source>/<original-relative-path>`.

New content includes additions and updated source versions. Confirmed local hash
matches are excluded across present catalog files in registered roots and files
already copied manually into the selected inbox. Filename, title and size guesses
never establish ownership. The entire remaining current source inventory is counted;
the limit is not permission to import the first 100 files of a larger source.

- Zero: retain an idle receipt; no processing or routine email.
- Above `--max-new-files` (default 100, independently per source): email the exact
  count for manual copying **and processing**, publish nothing, and continue with
  the next source. An unchanged pending manifest is not emailed repeatedly; known
  failed delivery retries, while interrupted/uncertain delivery is recorded and
  not resent blindly. A changed manifest or limit can generate another notice.
- Within the limit: stage the complete admitted batch privately, publish without
  overwrites, then invoke the same shared batch runner as `process-batch`.

The default source discovery/classification/copy budget is `--max-seconds 7200`.
It does not truncate the admitted source or limit downstream processing. Incomplete
observations/classification are failures, never false zero counts. Graph requests
already in flight can extend beyond that budget. Private cached file bytes are
bounded per source by `--max-cache-bytes` (default 20 GiB); retain digest proofs when
bytes are evicted. Increase the limit or handle the source manually if an admitted
batch needs more staging space. Interrupted downloads restart from the beginning.

Source metadata may not supply a usable SHA-256. Counting may require downloading
unfamiliar/changed candidates into private staging first. The large-batch rule
therefore prevents inbox publication and processing, not all network traffic.
Unchanged versions reuse verified source digests and local hashing caches with
size/inode/nanosecond modification/change-time checks. First reconciliation of an
old metadata-matched source can be expensive; old guesses are not trusted proofs.

OneDrive discovery uses its saved delta cursor to fetch changes, rather than
requesting each remote file every night. Exact local ownership links are saved in
`imports/<source>.sqlite3` against the remote item ID and content version. After the
first classification establishes these links, an unchanged nightly run checks each
linked copy's current filesystem signature directly. It does not build the broader
candidate inventory or read unchanged file contents. Catalog file IDs let these
links follow normal catalog-tracked moves and reorganizations.

A changed signature requires hash verification. A missing, changed or unsafe copy,
an unfamiliar remote version, or pending/unresolved work triggers broader matching
for the affected file sizes. Pending results are never cached as permanent
exclusions: a manual local copy added later must still be discovered. A fully linked
unchanged source avoids the inbox walk; a source with pending work may still need
one. Remote changes and local changes are both considered, so an unchanged OneDrive
folder does not conceal a deleted local copy.

Full ownership matching runs automatically every seven days. Use
`sync-sources --catalog PATH --inbox ROOT --full-reconcile` to force it sooner. This
rechecks the complete current source inventory against local candidates while
retaining valid content proofs and precise-signature hash caches; it does not force
remote redownloads or byte hashing of unchanged copies. Interrupted reconciliation
retains completed links and resumes its original reconciliation checkpoint. Its
completion time advances only after classification finishes without unresolved
files. OneDrive delta discovery remains independent of this ownership reconciliation.

The run summary reports `classification_mode`, `ownership_reused`,
`ownership_reclassified`, `local_inventory_built`, `local_candidates_indexed`,
`local_hashed_bytes` and `classification_seconds`, so a quiet run's remaining cost
can be distinguished from initial matching and changed-file work.

Underscore folders/descendants, root organizing catalogs, `_index.md` and remote
shortcuts retain the OneDrive discovery exclusions. Hidden and agent-context paths
that the local scanner excludes are ignored. Remote removal never deletes local
content; no files are uploaded. Different content at an occupied destination receives
a deterministic source/version suffix. Existing versions are preserved.

### Processing, notifications and recovery

Each source gets a separate `process-batch` run. Scan, quick dedupe and pack discovery
use the selected inbox; enrichment, filing, reorganization and review counts retain
the shared pipeline's catalog-wide behavior. Leftover files from another source can
be processed by a later run. One catalog orchestration lock prevents overlapping
sync/legacy-import/batch jobs; the coordinator reuses that lock for its batch calls.
The filing agent receives the source namespace as provenance context.

Completed runs retain normal shared review-backlog reporting: the count covers all
four review queues across the catalog. Clean completed processing with zero reviews
sends no routine email; the shared no-new-input suppression still applies. Source
and permanent or repeated transient failures, including zero-new-file failures, go
into the combined end-of-run
failure message rather than separate batch failure emails. Mail uses the existing
`RPG_LIBRARIAN_SMTP_*` and `RPG_LIBRARIAN_REVIEW_EMAIL_TO` configuration. Failed delivery
is persisted and returns nonzero. SMTP acceptance followed by a crash has uncertain
delivery; exactly-once email is not promised.

Private state beside the catalog includes `imports/sources.json` (registry/account
references), `imports/<source>.sqlite3` (discovery/history/hash proofs/admission),
`imports/local-hashes.sqlite3`, and `imports/cache/<source>/` (evictable staged bytes).
Back up the registry, source journals, catalog and token caches together. Keep state
on a local filesystem, not the SMB content share. Every run, including idle and
manual-required checks, saves `logs/sync-sources/<run-id>/summary.json`, with counts,
manifest, bytes, publication state, errors, delivery outcomes and linked batch logs.

Graph requests and redirected content transfers make up to five attempts for 429,
transient 5xx and connection failures. Transfers restart safely with a fresh download
URL after interrupted/short streams; retry delays honor `Retry-After` seconds or
HTTP dates, use exponential backoff with jitter, and respect the source deadline.
Credentials renew silently before expiry; Graph 401 triggers one forced renewal and
retry. Persistent sign-in failures remain actionable failures.

Request records are written to private `<source>-requests.jsonl` files alongside the
summary. They identify source/phase/operation/item, HTTP status, safe service error
codes, request IDs, attempt, duration, byte counts and retry delays. Token records
include expiry and renewal outcome, never token contents. Signed download URLs,
authorization headers and raw response bodies are excluded. The summary records
classification progress, unresolved items, local hashing cost, last request and
request-log location, even if classification fails.

An isolated exhausted transfer does not stop classification of other files. Any
unresolved item blocks admission of the entire source; three consecutive exhausted
files pause the source to avoid hammering an unavailable service. Source-budget
exhaustion produces a `deferred` outcome with saved progress, exits zero, and never
sends a failure email, even across repeated nights. It resets the temporary-failure
counter. The existing timer retries on its next scheduled invocation; a manual
rerun also resumes progress. Temporary service failures defer quietly for the first
two consecutive runs. The third consecutive service failure (and each subsequent
one until recovery) becomes `failed`, returns nonzero, and joins the combined
failure notification. A successful source lifecycle also resets the counter.
A deferred receipt is not a completed source sync.

Small-batch admission and each published file are journaled. Rerunning resumes an
unfinished admitted batch **before** the zero-new-files decision, even if the source
files are now locally owned. Processing-only handoffs can resume without source
access. A different inbox cannot silently take over an unfinished batch. Stale
admissions that have published nothing can be cancelled and rediscovered; partial
publication retains its recorded snapshot. Crash recovery cleans up orphaned batch
children before new work. Completed files and catalog decisions survive reruns.

Existing `imports/brendan.sqlite3` source identity is adopted automatically without
moving files or discarding revisions. Unfinished previously published work is carried
into a processing handoff. Existing SHA-256 downloads seed verified content history;
metadata ownership guesses require exact reconciliation. `import-status`,
`import-reviews`, and `import-review` remain available for historical records.
`import-run` exits with migration guidance; its old transfer-budget/partial-processing
flags have no automatic equivalent in the whole-source admission model.

### Nightly invocation

The production `process-brendan.zsh` is a one-shot selected-source wrapper;
`sync-sources.zsh` handles all enabled sources. The old five-minute forever loop is
retired. For example, a user-managed nightly scheduler can invoke:

```bash
/home/eriksalt/data/rpg-librarian/sync-sources.zsh
```

Production uses the systemd user units in `scripts/systemd/`, installed under
`~/.config/systemd/user/`. The timer runs at **03:00 America/Los_Angeles**, catches
missed runs after startup/resume, and does not wake a sleeping machine. User
lingering must be enabled to run while logged out (already enabled on this host).

The service runs the CLI directly from `~/data/rpg-librarian`, with an explicit
PATH for Claude, the editable app installation and system tools. It uses the app's
existing `.env`, source registry and signed-in accounts. It verifies that the inbox
is writable and on the mounted CIFS share before running. A mount/preflight failure
appears in the journal before the app starts, so no application email is sent for
that failure. App notification policies and the default 100-file threshold apply
normally once the CLI starts. Sign in interactively before unattended operation.

Long runs have no startup time limit. The same service cannot overlap itself; the
catalog lock also protects against simultaneous manual batch/sync jobs. Failed runs
are not automatically retried in a loop. Output goes to the journal; application
receipts remain in `~/data/rpg-librarian/logs/sync-sources/`.

```bash
# Install/update from the source checkout, then enable the nightly timer:
mkdir -p ~/.config/systemd/user
cp scripts/systemd/rpg-librarian-sync.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rpg-librarian-sync.timer

# Schedule, recent output, and optional manual execution:
systemctl --user list-timers rpg-librarian-sync.timer
journalctl --user -u rpg-librarian-sync.service -n 100 --no-pager
systemctl --user start rpg-librarian-sync.service

# Disable future scheduled runs (does not stop an active run):
systemctl --user disable --now rpg-librarian-sync.timer
```
