# Asset pack support: idea

Workshop outcome of 2026-10-02. Nothing is built. Everything under "Working direction" was accepted by the user in conversation unless marked otherwise. Quality judgments are of the design's apparent potential, made against the approved rubric in [intent.md](intent.md); they are not demonstrated performance.

## Intended effect

Make map packs, token sets, audio sets, STL sets and similar collections catalogable as one thing. Their files have no identity to look up individually; their identity is collective and usually comes from the name of the containing folder or its parent. One decision, lookup and product assignment should cover a pack of thousands of generically named files, including packs with no external search matches.

The core: add `pack` as a second entry type on the [entry table](../entry-table/item.md), and form packs from folder evidence judged by an LLM instead of from a fixed rule.

## Working direction

### Schema

- A new pack table holds pack definitions. Each pack stores its root folder, the evidence summary and reasons behind its formation, and its own product and disposition.
- `file.pack_id` is a nullable foreign key into the pack table, so membership is recorded on the file.
- A file that belongs to a pack loses its entry row. The pack gets an entry (a new `pack` type, with a nullable `pack_id` foreign key on `entry`), so tools, evidence, errors and review flags address a pack like any other entry.
- A migration adds the table and columns.

### Finding packs

1. **Deterministic evidence walk.** Collect per-folder evidence: file counts, file-type mix (packs are mostly vtt tokens, maps, audio, STL, not PDFs), numbered-name runs such as `name_###`, and sibling folders that look like variants of the same files (img vs png, day vs night, gridded vs gridless).
2. **Media-dominance gate.** A folder where documents dominate is never offered as a pack ("you won't find a pack that is just 4 PDFs"). Settled folders are skipped too.
3. **Folder-name search.** Each remaining candidate folder gets one Google search on its folder name plus its parent's name, cached by normalized query. Hits are corroboration, not proof: a generic name like "Maps" can match unrelated products, and no hits do not argue against a pack.
4. **Top-down LLM classification.** Starting at each scan root, the LLM sees the evidence summary and search hits for one folder and its immediate children, with sibling folders batched into one call. It answers *pack* (descent stops; section subfolders are absorbed), *container* (descend into named children), or *no packs*. Answers are stored with a fingerprint of the folder's contents, so unchanged folders are not asked again.
5. **Validation.** A deterministic check confirms returned paths exist, do not overlap, and claim each file at most once. Failures go to review instead of becoming packs.

Where this runs is open: the evidence walk fits the end of scan, but as far as was seen only `enrich` calls an LLM today (`enrichment/text_analysis.py`, model from an environment variable), so the LLM step may belong to an enrich-like stage.

### Membership and ownership

- Every file under a pack root is a member, including a short PDF, text description or license file. Those documents' sample text feeds the pack's pooled text analysis. A member PDF gives up its individual lookups (ISBN, dtrpg, rpggeek); this was accepted for minor documents.
- **The pack owns the decision.** It carries its own product and disposition, and members inherit them. Placement and reorganize read a member's destination from its pack.
- **Lossless formation.** A folder becomes a pack only if no existing decision is destroyed: all its files are unfiled, or all are already filed to the same product with the same disposition (the pack takes that decision). A mixed folder stays as loose files and is flagged for review. This lets the roughly 34k-file live catalog adopt packs gradually.

### Enrich

- dtrpg, rpggeek and Google lookups run once per pack, using folder names. ISBN lookup does not run for packs.
- Text analysis pools the sample text of the pack's files, up to a limit.
- The candidate-folder search from pack formation is stored as the pack's `google_search_result` when the pack is created, so `enrich` does not search again.

### Tools and skills

- All tools handle pack entries as well as file entries, including reporting, updating, and setting the product.
- New `report-pack` tool: all subdirectories and files in a pack.
- New add-file-to-pack and remove-file-from-pack tools (add can also move a file between packs). They accept a folder path as well as a file, so one call fixes a boundary.
- Manual add or remove is pinned: neither a rescan nor an LLM re-decision may overrule it. New files under a pack root join automatically with no LLM call, unless they were removed on purpose. A file removed from a pack becomes an ordinary unfiled entry.
- The `process-batch` and `review-items` skills must work correctly with packs.

## Why these choices

- **Evidence plus LLM instead of a fixed depth.** The existing `PACK_DEPTH = 3` in `enrichment/queries.py` splits deeper packs, and a generic-folder stoplist (the agent's first proposal, dropped) would guess at folder meaning. Folder evidence lets the LLM learn the layout from what is there.
- **Top-down, one level at a time.** Cost scales with folders along container chains, not files, and a thousand-file pack costs one decision.
- **Search only gated candidates.** The live catalog has 4,412 folders (measured read-only), against the 119 requests per-pack asset lookup cost. Serper is paid and rate-limited. Most of those folders are already-organized library folders that lossless formation leaves alone, but the real load has not been measured.
- **Pack owns the decision.** Otherwise members with no entry would drop out of `compute_placements`, which joins `file` to `entry`, and out of the pending count.
- **Pinned folder-level corrections.** Fingerprints would otherwise make the LLM re-decide a folder a person had fixed.

## Costs accepted

- Disposition is no longer file-only. This **reverses the entry-table decision** to keep `disposition` on `file`; packs need their own disposition and placement a second path.
- A member cannot have its own disposition unless first removed from its pack.
- Member PDFs lose individual lookups; a real book absorbed into a pack would lose its strongest evidence. The media-dominance gate and stored reasons are the protection.
- Pack formation depends on a search key and an LLM, and is less certain offline.
- A pinned wrong correction stays wrong until corrected again.
- Container folders such as "Maps" that pass the gate still cost a search.

## Qualitative assessment at close of workshop

Judgments of apparent potential, against the [Quality rubric](intent.md#quality-rubric):

- **Pack integrity:** strong. Evidence-driven boundaries, documents kept as members, the overlap check, and pinned corrections. Weak point: wrong LLM boundaries until validated or corrected.
- **Evidence fidelity:** good. The evidence behind each decision is stored on the pack, hits are corroboration only, and formation cannot erase existing decisions.
- **Usefulness with sparse evidence:** strongest. One decision covers a pack, even with no hits.
- **Processing economy:** good in design, unmeasured. The gate, cache, fingerprints and reused search bound cost to candidate folders.

## Open questions (for flesh-out)

*Update 2026-10-02: several of these were resolved in the flesh-out and are now recorded in [intent.md](intent.md), which is current where it differs from this document. Resolved: scan versus a separate stage (a separate `find-packs` command), pinned corrections (a pack is never re-judged), and the root and placement direction.*

- Table and column design, and migrating the `disposition` change.
- The LLM prompt and the evidence summary format.
- The rule for skipping searches on generic folder names (a cost control, not a boundary rule).
- Whether pack formation is a scan step or a separate stage.
- How `reorganize` places pack members, and how a folder's subpath is kept.
- How the review flow presents unvalidated or mixed folders.
- How the entry-table migration (`0005`) and live catalog adopt a non-file entry type.

## References

- [intent.md](intent.md): outcome and approved rubric.
- [entry-table](../entry-table/item.md): the `entry` table this builds on.
- [per-pack-google-lookup](../per-pack-google-lookup/item.md): the earlier per-pack Google search and its `PACK_DEPTH` rule.
- Code inspected: `services/placement.py`, `services/update_product.py`, `enrichment/queries.py`, `enrichment/text_analysis.py`, `model/Entry.py` under `apps/rpg-librarian/src/rpg_librarian/`.
