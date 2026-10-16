# Idea history

The original Brendan-only idea below was expanded with owner approval into a named
source registry and provider interface. Current approved scope and behavior are in
[intent.md](intent.md); the completed design and verification are in [plan.md](plan.md).
Brendan-only scope statements below are historical, not current requirements.

# Brendan import using the shared batch process

Refactor the existing Brendan import workflow to check a registered source for
new content and reuse the completed
[process-batch CLI](../process-batch-cli/item.md) for downstream processing. The owner
intends to run this command once each night using their machine's scheduler. Most
nights are expected to have no new content, so that path should simply exit.

The source in the current discussion is the registered Brendan OneDrive location.
This idea does not establish support for additional source providers or install a
nightly schedule.

## Agreed meaning of new content

Consider both newly added source files and updated content in previously seen
files. The owner explicitly approved including updated versions after discussing
the performance implications.

Before applying the batch-size threshold, exclude files confirmed already present
locally by matching content hashes. Filename, folder, title, or file-size similarity
alone does not satisfy this requirement. The threshold counts remaining files that
need importing, not all source changes or documents already owned.

Previously verified, unchanged source content can be recognized through saved
history. An updated file remains a candidate unless its current content is also
confirmed already present locally. Detecting an updated source file does not itself
authorize discarding or replacing an older local version.

## Command behavior

The command selects a registered source and accepts a destination inbox location
and a maximum automatic file count. The threshold must be a command-line option
with a default of **100**; exact option names are not yet designed. The owner expects
to use `/phinneas/rpg/inbox` as the destination almost every time; this is an expected
argument value, not an agreed hardcoded default.

After excluding confirmed hash matches:

- **Zero files:** exit without running process-batch. Do not process existing inbox
  or catalog work on these otherwise quiet nights.
- **More than the threshold:** email the owner that the batch requires manual
  handling. Do not copy the batch into the destination inbox or start process-batch.
  The owner will perform the entire copying and processing workflow themselves;
  the next nightly run is not responsible for completing that manual workflow.
- **Between one and the threshold, inclusive:** copy the remaining files into the
  inbox specified on the command line, then run the same processes as the shared
  process-batch command, using the intended catalog and that inbox.

The threshold is a decision about the entire pending batch, not permission to take
only the first 100 files from a larger one. The shared process-batch behavior,
including its local summaries, safe rerunning, processing scopes and selective
review-backlog notification, remains the downstream reference. This item has not
selected separate downstream notification rules.

## Accepted performance tradeoff

The existing source discovery already tracks content versions and OneDrive change
cursors. Including updates can use incremental metadata checks rather than
redownloading every source file on every night. This does not establish a measured
runtime guarantee for the refactor.

Exact ownership checks are the potentially expensive part. The current catalog
stores SHA-256, while source hash metadata is not guaranteed to provide a directly
comparable supported hash for every file. The owner accepted that confirming
unfamiliar or changed content may require additional local hashing, a comparable
hash index, or downloading a candidate to calculate SHA-256 before deciding whether
it is already owned and whether the remaining batch exceeds the threshold.

Consequently, the large-batch rule prevents automatic inbox transfer and processing;
it does not promise that counting requires no file-byte reads or temporary downloads.
The implementation strategy has not been selected. Saved verified history should
avoid treating unchanged, already-handled source content as new each night.

## References and remaining detail

- [Existing source discovery](../../apps/rpg-librarian/src/rpg_librarian/imports/discovery.py)
  tracks content versions and change cursors.
- [Existing matching](../../apps/rpg-librarian/src/rpg_librarian/imports/matching.py)
  currently includes metadata-based ownership assumptions as well as an exact-hash
  lookup; metadata guesses must not stand in for the approved hash-match exclusion.
- [Shared batch runner](../../apps/rpg-librarian/src/rpg_librarian/batch/runner.py)
  is the downstream process to reuse.
- [OneDrive incremental changes](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)
  and [source hash metadata](https://learn.microsoft.com/en-us/graph/api/resources/hashes?view=graph-rest-1.0)
  supported the performance discussion. Microsoft documents that SHA-256 metadata
  is unsupported; the refactor must not assume it is available for every source file.

CLI spelling, hash-index/download strategy, which local locations are compared,
partial-transfer recovery, destination collisions/version coexistence, interaction
with the existing source journal, and repeated large-batch notification policy remain
detailed-design work. No choice of scheduler or automatic schedule installation was
requested. This save records the approved idea without beginning planning or
implementation.
