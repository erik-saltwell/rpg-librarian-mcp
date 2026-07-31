# `update_product` — spec

Design reached via brainstorm on 2026-07-30. Status: **complete**,
implemented the same day. Referenced from `tools_spec.md` (tool 11). This
is the `identify_product`-style write tool `rpg_lookup_spec.md`'s "Open
items" section explicitly deferred: "takes a `ProductLookupDetails` ...
and writes/updates `Product`, setting `identification_method`."

## Implementation notes

- New `ProcessingStage.link_product` value
  (`model/ProcessingStage.py`) — `Error.stage` is a plain `String` column
  (no `CHECK` constraint, unlike `media_type`'s `TolerantMediaType`), so
  adding it needed no migration.
- `commands/UpdateProductCommand.py` implements the two-step flow exactly
  as designed below: `run()` does entry-resolution + find-or-create in its
  own `session_scope`, then delegates the per-entry stamping to
  `self.process(...)` (inherited from `UpdateBaseCommand`), always passing
  `force=False` since this tool never exposes a `force` param.
  `_resolved_product_id` is stored on `self` between the two steps — safe
  because `run()` fully owns one command instance per call (`mcp/
  update_product.py` constructs a fresh `UpdateProductCommand` per tool
  call), not because `UpdateBaseCommand.process_one` is guaranteed
  single-threaded in general.
- Matching (`_find_or_create_product`) builds its `WHERE` clause from
  whichever fields are non-`None`, using `func.lower(column) ==
  value.lower()` for the free-text fields (`title`/`description`/
  `artists`/`publisher`/`system`) and an exact `==` for `year`, per the
  brainstorm's Q2/Q6 decisions.
- `mcp/update_product.py` registers the tool per the signature below and
  is added to `REGISTRARS` in `mcp/__init__.py`.

## Goal

Give the LLM a way to link cataloged files to a `Product`: find an
existing `Product` matching caller-supplied details, or create one if none
matches, then set `product_id` on every `Entry` under a file-or-directory
path. This is the write half of product identification; `search_rpg_geek`,
`lookup_rpg_geek_product`, `search_dtrpg`, and `lookup_isbn` (all
read-only) are the tools a caller would typically use first to gather the
details passed in here.

## Signature

```python
async def update_product(
    path: Path,
    title: str,
    identification_method: IdentificationMethod,
    ctx: Context,
    process_recursively: bool = False,
    description: str | None = None,
    artists: str | None = None,
    publisher: str | None = None,
    year: str | None = None,
    system: str | None = None,
) -> dict[str, object]:
    """Find or create a Product matching the given details, then link
    every entry under `path` to it.

    `path` must be an absolute path, and may be a single file or a
    directory; directories are non-recursive unless `process_recursively`
    is set (ignored for a single-file `path`). `title` is required; all
    other Product fields are optional. `identification_method` records how
    the caller identified this product (e.g. `manual`, `isbn_match`,
    `rpggeek_match`) -- there is no default, the caller always states it
    explicitly.
    """
```

Field set is `Product`'s own columns (`model/Product.py`), not
`ProductLookupDetails`'s external-lookup shape -- deliberately sidesteps
the "creators -> artists" / `year_published: int` vs `year: str`
reconciliation `rpg_lookup_spec.md` flagged as unresolved. A caller piping
a `ProductLookupDetails` result in here (e.g. from `lookup_isbn`) maps
`creators` and `year_published` onto `artists`/`year` themselves; this
tool does not do that mapping.

No `force` param. Every other `update_*` tool has one to bypass a "skip if
unchanged" check, but there's no equivalent stale/fresh state here --
`should_process` below always resolves to a real state (matches the target
product or doesn't), so a `force` flag would have no bypass to perform.

## Flow

1. **Resolve entries under `path`.** Same resolution `UpdateBaseCommand`
   already does (`_resolve_entries`): single file -> that file's `Entry`
   (must already be cataloged, else `ValueError`); directory -> its
   `Entry` rows, recursive per `process_recursively`. If this resolves to
   an empty list, raise immediately -- **before** touching `Product` at
   all. Creating a `Product` that ends up linked to nothing is silent junk
   data (unlike e.g. `update_metadata`'s harmless `scanned: 0`), and an
   empty match here is almost certainly a wrong `path` or a
   forgot-to-`update_catalog`-first mistake -- worth surfacing loudly
   rather than quietly creating an orphan row.

2. **Find-or-create the `Product`.** Query `Product` for rows matching
   every field the caller actually passed (`None`/omitted fields are not
   constrained) -- exact match for `identification_method` is never part
   of this comparison (see below), exact match for `year`, case-insensitive
   match for `title`/`description`/`artists`/`publisher`/`system` (free
   text -- "Call of Cthulhu" vs "call of cthulhu" must not create a
   duplicate `Product`).

   - **Zero matches:** create a new `Product` from the passed fields
     (unpassed optional fields stay at their model defaults, e.g. `system`
     defaults to `Product.UNKNOWN_SYSTEM`), commit, use its `id`.
   - **Exactly one match:** reuse it, **untouched** -- no upsert of its
     fields from this call's args, no bumping `identification_method` even
     if this call's differs from what's stored. `identification_method` is
     excluded from the match query for exactly this reason: a `Product`
     created `manual` should still be found and reused by a later call
     that passes the same title/system but a different
     `identification_method` (e.g. after a retroactive `isbn_match`
     lookup confirms it) -- treating method as part of identity would
     make near-identical `Product`s multiply just because the caller
     identified the same thing two different ways.
   - **Two or more matches:** raise `ValueError` naming the ambiguity
     (e.g. which fields matched, how many rows). Do not guess, do not
     create a new `Product` as a fallback -- silently picking one risks
     linking files to the wrong product; silently creating a duplicate
     defeats the purpose of matching at all. The caller should retry with
     more distinguishing fields (most usefully `system`).

3. **Stamp `product_id` onto every resolved entry**, via
   `UpdateBaseCommand`:
   - `should_process(session, entry)` = `entry.product_id !=
     resolved_product_id` -- true whether the entry's `product_id` was
     previously unset *or* pointed at a different product. There is no
     `force`-gated distinction between those two cases (see "No `force`
     param" above) -- a plain call overwrites either.
   - `process_one(session, file_path, entry)` sets
     `entry.product_id = resolved_product_id` and `session.merge`s (or
     assigns + `session.add`s) it.
   - Everything else (per-entry transaction boundary, error capping,
     progress reporting) comes for free from `UpdateBaseCommand.process`.

## Architecture: two steps, not one `UpdateBaseCommand` subclass alone

`UpdateBaseCommand` (`commands/UpdateBaseCommand.py`) is shaped for
**independent per-entry work** -- `should_process`/`process_one` are
called once per `Entry`, each entry's success/failure and transaction are
independent of every other entry's. The find-or-create-`Product` step is
not that: it must happen exactly once per call, before any entry is
touched, and its outcome (`resolved_product_id`) is shared by every
subsequent per-entry call.

Resolution: do NOT smuggle run-scoped state into `process_one` via
`self`-caching on first call (considered and rejected -- would make
`UpdateBaseCommand`'s contract quietly depend on serial, single-threaded
entry iteration, which is true today but not part of its documented
contract). Instead:

- The find-or-create step (including the Q8 empty-entries check) runs in
  its own `session_scope`, ahead of and outside of
  `UpdateBaseCommand.process`.
- `UpdateProductCommand(UpdateBaseCommand)` then implements the trivial
  per-entry `should_process`/`process_one` above, parameterized by the
  already-resolved `product_id` (passed into `__init__` or set right
  before calling `process`).
- `_resolve_entries` therefore runs twice -- once outside (to check
  emptiness before creating a `Product`), once inside
  `UpdateBaseCommand.process`'s own `session_scope`. Accepted redundancy:
  it's a cheap read query, correctness isn't affected (entries aren't
  expected to change mid-call), and it avoids either duplicating
  `UpdateBaseCommand.process`'s transaction/progress-reporting machinery
  or bending that class's contract to fit a run-scoped precondition it
  wasn't designed for.

## Response shape

Same `UpdateResult`-derived dict every other `update_*` tool returns,
plus `product_id` and `created`:

```json
{
  "scanned": 3,
  "skipped": 1,
  "succeeded": 2,
  "errored": 0,
  "errors": [],
  "product_id": "3f1c...-uuid",
  "created": true
}
```

Kept consistent with `update_metadata`/`update_catalog`'s shape rather
than a bespoke `{"product_id", "created"}`-only response -- per-entry
writes here can still fail (DB constraint issue, entry deleted mid-run),
and a caller (LLM) parsing several `update_*` tools' output benefits from
one consistent shape rather than special-casing this one.

## Open items / explicitly out of scope

- **`creators` -> `artists` / `year_published` -> `year` reconciliation**
  -- still not resolved (carried over from `rpg_lookup_spec.md`). This
  spec's `title`/`artists`/`year` fields mirror `Product`'s current
  columns as-is; a caller piping a `ProductLookupDetails` result into
  `update_product` must map `creators` (list) onto `artists` (str) and
  `year_published` (int) onto `year` (str) themselves.
- **No update/upsert of an existing matched `Product`.** Confirmed
  explicitly (see step 2): matching only ever resolves an id, never
  mutates a previously-created `Product`'s stored fields. A future
  `merge_products`/`edit_product`-style tool would be a separate, later
  design if this gap turns out to matter in practice.
