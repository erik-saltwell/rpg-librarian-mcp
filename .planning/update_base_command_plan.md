# UpdateBaseCommand Design Plan

Design decisions for a shared base command that per-entry update commands
(metadata extraction, barcode reading, OCR, ...) derive from, reached via
brainstorm on 2026-07-29. This captures the design shape only — no
implementation yet.

## Problem

`UpdateCatalogCommand` is the only fleshed-out `CommandProtocol`
implementation today, and it is *not* a good base to derive from: it walks
the filesystem directly and creates/deletes `Entry` rows, because that's
the one command whose job is building the catalog itself. Every other
planned command (metadata extraction, barcode reading, OCR text) instead
writes rows keyed on `entry_id` (FK to `Entry`) — they operate on an
already-cataloged file, not a raw path on disk. `UpdateBaseCommand` is the
shared base for *that* category of command: "iterate cataloged entries in
scope, process each one, handle errors/progress uniformly."

## Iterate Cataloged Entries, Not the Filesystem

`UpdateBaseCommand` resolves `starting_path` to `Entry` rows already in the
catalog (via `entries_by_parent` / `entries_under` / an exact-path lookup),
not via `walk_filesystem`. This is why `UpdateCatalogCommand` does not
derive from it — it's the one command that predates the catalog existing
for a given file.

A consequence: these commands assume `update_catalog` has already run.
They do not walk the disk, create stub `Entry` rows, or otherwise try to
paper over "this file isn't cataloged yet."

## Scope Resolution & Fatal Conditions

- **Single file, no matching `Entry`**: raise. Running an update command
  against a path that was never cataloged is a usage error — the caller
  should run `update_catalog` first, not get a silent no-op.
- **Directory, path doesn't exist on disk**: raise (same check
  `walk_filesystem` already does).
- **Directory, exists but zero cataloged entries in scope**: *not* an
  error. A directory can legitimately contain zero files in scope (all
  subfolders, or a folder that's out of scope for this command), so an
  empty result is a valid outcome — only a *named single file* that isn't
  cataloged is treated as an intentional-therefore-must-exist request.
- No filesystem re-walk is performed to detect "some files on disk aren't
  cataloged yet" for a directory scan — that would reintroduce a full disk
  scan into a command that's supposed to be catalog-only, and duplicate
  `update_catalog`'s job.

## `should_process` / `process_one` Split

Two abstract methods, deliberately asymmetric in what they need:

```python
def should_process(self, session: Session, entry: Entry) -> bool: ...
def process_one(self, session: Session, file_path: Path, entry: Entry) -> None: ...
```

- **`should_process`** answers "is the existing result for this entry
  stale or missing?" — it needs `session` because only the subclass knows
  its own result table(s) (e.g. compare `FileMetadata.updated_at` against
  `entry.updated_at`); the base has no generic way to compute this.
- **`process_one`** does the actual extraction/lookup and persists its own
  result row(s) via `session.add`/`session.merge` (upsert-by-primary-key,
  since these are all `entry_id`-PK'd tables per the metadata plan). It
  raises on failure and does **not** commit or roll back — the base owns
  the transaction boundary:
  - success → base commits, clears any stale `Error` row for this
    `(entry_id, processing_stage)`.
  - exception → base rolls back, records/updates an `Error` row instead.
- **`force` bypasses `should_process` entirely** — the base does
  `if force or self.should_process(session, entry):` and short-circuits,
  so a forced run never even queries the result table. `should_process`
  only ever answers "stale or missing," never "should we skip" — `force`
  means the same thing for every command, with no per-subclass
  reinterpretation.

`process_one` receives the resolved absolute `file_path` directly (the
base already computed it while resolving scope) rather than making every
subclass re-derive it from `catalog.to_absolute(entry.path)`.

## Media-Type Applicability Is Not a Base Concept

Whether a command's logic applies to a given entry's `media_type` (e.g. a
PDF-specific extractor doesn't apply to an audio file) is left entirely to
the subclass, inside `process_one` — it just does the generic part (or
nothing) and returns without raising when there's nothing type-specific to
do. No separate `applies_to(entry) -> bool` abstract method: every
subclass would implement it the same way `process_one` already has to
(checking `entry.media_type` and early-returning), so a third abstract
method would add surface area without adding capability.

## `ProcessingStage` (renamed from `ErrorStage`)

`ErrorStage` is renamed to `ProcessingStage` and generalized beyond the
`Error` table — the same enum is meant to be reused later for provenance
tracking elsewhere (e.g. `Product` identification/source tracking), so it
gets one honest name now rather than carrying an `ErrorStage` /
`ProcessingStage` split forward once a second consumer shows up. Existing
member `populate_file_data` carries over; new members are added as each
command lands (e.g. `extract_metadata`, `read_barcode`, `ocr_text`).

Every `UpdateBaseCommand` subclass declares its stage via a required
constructor argument, passed through to the base:

```python
class UpdateBaseCommand(ABC):
    def __init__(
        self,
        catalog: Catalog,
        processing_stage: ProcessingStage,
        max_errors: int = 50,
    ) -> None:
        self.catalog = catalog
        self.processing_stage = processing_stage
        self.max_errors = max_errors

    @abstractmethod
    def should_process(self, session: Session, entry: Entry) -> bool: ...

    @abstractmethod
    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None: ...
```

A concrete subclass only has to write its own constructor (for its own
parameters) plus the two abstract methods:

```python
class UpdateMetadataCommand(UpdateBaseCommand):
    def __init__(
        self,
        catalog: Catalog,
        extractor_registry: ExtractorRegistry,
        max_errors: int = 50,
    ) -> None:
        super().__init__(catalog, ProcessingStage.extract_metadata, max_errors)
        self.extractor_registry = extractor_registry

    def should_process(self, session, entry) -> bool: ...
    def process_one(self, session, file_path, entry) -> None: ...
```

This does mean touching the already-drafted `Error`/`ProcessingStage`
migrations and anywhere `ErrorStage` is referenced today.

## Shared Result Shape

One concrete `NamedTuple` lives on `UpdateBaseCommand` and is used as-is by
every subclass — no per-subclass result type:

```python
class UpdateResult(NamedTuple):
    scanned: int
    skipped: int
    succeeded: int
    errored: int
    errors: list[ProcessingError]  # capped to max_errors, same as UpdateCatalogCommand
```

`removed` (from `UpdateCatalogCommand`'s result) does not appear here —
deleting a row because its underlying file vanished is a catalog-scan
concern, not something any `UpdateBaseCommand` subclass does. Nothing
about metadata/barcode/OCR needs a divergent shape, so a per-subclass
generic result type (echoing `CommandProtocol[ResultType]`'s `TypeVar`)
would be speculative generality; a future command needing an extra counter
can override then.

## Progress Reporting & Commit Granularity

Reuse `UpdateCatalogCommand`'s existing pattern as-is: per-file commit
(not batched), and throttled `ctx.report_progress` calls (only fired when
the whole-percent value changes, not on every file).

## Open Items (Not Yet Decided)

- Exact enum member names/count for the new `ProcessingStage` values
  beyond `extract_metadata` (barcode/OCR stages land when those commands
  are designed).
- Whether/how `list_directory_entries` and similar read tools should
  surface per-stage error state now that `Error` will carry more than one
  non-catalog stage.
- `UpdateMetadataCommand`'s own constructor parameters (extractor
  wiring) and its `should_process`/`process_one` bodies — out of scope for
  this base-class design.
