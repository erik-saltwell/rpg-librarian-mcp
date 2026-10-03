---
name: "Pack migration"
status: complete
---

# Pack migration

Build the migration script or tool that moves the live catalog (`~/data/rpg-librarian/catalog.db`, about 34k files) to the pack-aware schema from [asset-pack-support](../asset-pack-support/item.md), and run it on live data before any further processing (scan, enrich, filing) happens against the new design.

Scope as understood so far, not yet designed:

- Running the schema migration for packs (`0006`, built in asset-pack-support) on the live catalog.
- Adopting already-filed asset products as packs. The user's direction (2026-10-02): the migration runs `find-packs` on each folder under a product line to identify the packs, under the lossless-formation rule (a pack takes the product and disposition its files already share). Still open for this item: whether folders whose files already share one product can skip the search and LLM calls, as a cost saving.
- Following the approach of [entry-table](../entry-table/item.md): back up the live catalog first, rehearse on a copy, compare before and after, and keep a working downgrade.

## Documents

- [background.md](background.md): handoff from asset-pack-support: live-catalog safety, what exists, the open adopt-mode problem, the build-and-verify process, and reusable tools. **Start here.**
- [plan.md](plan.md): agreed five-phase process, accepted workshop refinements, and the settled design decisions. Phases 1-4 checked off.
- [progress.md](progress.md): **current handoff**: what was built, every check run and its result, the rehearsal files, the subpath deviation, and the phase 5 runbook.
- [checks.md](checks.md): accepted migration checks: schema-only preservation, adoption comparison with differences permitted by specific record/field, and offline application checks on the rehearsal copy; rationale, limitations, and planned demonstrations.

## Facts learned while building asset-pack-support (2026-10-02)

- The schema migration exists: `0006_add_packs.py`. Any CLI command, or a `serve`
  start, on the new code upgrades the catalog it opens. So the live catalog
  (`~/data/rpg-librarian/catalog.db`, still at `0005`) must be backed up before anything
  touches it with the new code, and nothing should run against it until this item is
  ready. An upgrade and downgrade of a live copy was rehearsed: rows identical, 0.7 s.
- **`find-packs` as built will not adopt filed products.** It skips *settled* folders
  (no unfiled files), and every live file is filed (33,109 keep, 762 duplicate, 363
  discard, 18 superseded). A dry run on a live copy asked nothing. Running `find-packs`
  on the folders under each product line needs a mode that also considers filed
  folders: for example, an adopt option that treats a folder whose files share one
  product and disposition as a candidate. Its lossless rule already makes such a pack
  take that decision.
- Useful pieces: `find-packs --dry-run` stores its answers, so a later real run forms
  the proposed packs without new model calls. `--limit` caps calls. `folder_judgment`
  records every outcome for review. Comparison tools that understand packs are in
  `~/data/rpg_test_tools/` (`catalog_state.py`, `compare_catalogs.py`,
  `snapshot_placements.py`, `migrate_copy.py`).

## Related

- [asset-pack-support](../asset-pack-support/item.md) (complete, uncommitted): the feature whose schema this migrates to.
- [entry-table](../entry-table/item.md): the previous migration (`0005`) and its verification approach.

## Completion (2026-10-03)

The live catalog `~/data/rpg-librarian/catalog.db` is migrated to the pack schema (`0006`) with 117 filed asset products adopted as packs (7,608 member files), applied from the reviewed rehearsal list `~/data/rpg_test_snapshots/pack-migration/rehearsal/list.json` after the user's hand checks. Verified on live: schema-only validator PASS after the upgrade; full independent validator PASS (every file's effective disposition and product unchanged, all 34,252 placements identical, only the planned rows deleted); `reorganize --dry-run` identical to the pre-migration baseline (0 to move); `list-unfiled` unchanged; integrity ok. Live sha256 now `f9120066…`; the pre-migration backup (`backups/catalog.pre-pack-migration.rawcopy.db`, `3e73f6af…`) is the complete rollback. Details and the full verification record: [progress.md](progress.md). Nothing has been committed. Follow-ups noted there: optional export of the 42 removed resolved review-flag notes, the `duplicate_of.entry_id: null` presentation for 55 duplicates of members, cleanup of the `-0005` worktree and rehearsal copies, and avoiding a first `scan --force` over packs.

## Fresh-thread handoff (2026-10-03, before implementation; superseded by the resume note and progress.md)

- Read the project workflow and context, then this item, [background.md](background.md),
  [plan.md](plan.md), and [checks.md](checks.md). Both workshops are finished; the
  process and check refinements are accepted, not tentative suggestions.
- Current checkout verified on `tooling-refactor`, with uncommitted pack-support code,
  these work-item documents, and separate `clear_errors` work. Preserve existing edits;
  the feature is not represented by committed HEAD alone. No commits were made here.
- No pack-migration backup, validator, adoption implementation, rehearsal, or live run
  has been performed. Earlier pack-support verification in the background is historical
  evidence for that feature, not completion of this item's checks.
- The live catalog's recorded revision is `0005`; it was not rechecked in this thread.
  Verify current state with direct read-only access. Begin implementation with phase 1
  backup before opening live data through any auto-migrating application command or
  server. Build and rehearse on copies until the verified live cutover.
- (Superseded 2026-10-03: implementation started; status is `implementing`. See the
  resume note and [progress.md](progress.md).)

## Design decisions settled (2026-10-03)

The four open decisions were settled with the user, one at a time. Full text and the
measurements behind them are in [plan.md](plan.md#settled-design-decisions).

1. **Scope:** check every product folder under a product line; adopt only library-root
   folders whose eligible files are all `keep` for one product, that are the product's
   own folder, and that pass the media gate. Flat products, mixed, and non-`keep`
   folders stay loose.
2. **Detection:** no shortcut. Use the existing gate, search, model, and lossless
   formation, via a new adopt mode that considers filed folders and starts at the
   product line folders. The gate stays.
3. **Retention:** accept deletion of adopted files' entry-keyed rows; carry nothing
   onto the pack; skip a folder with an open review flag or error on a member.
4. **Baseline:** capture it on a hashed copy of the verified backup with the `0005`
   code (worktree of `5c8b268`); never open the original with application code.

The live catalog had changed since the background handoff (49 unfiled missing files, 50
missing files, inbox scanned 2026-10-03 01:02), so phase 1 needs a fresh baseline.
Unmeasured: the real search and model-call load; measure with `--dry-run --limit` on a
copy. Still to design with the adopt mode: the exact `folder_search` and
`folder_judgment` rules for the validator.
