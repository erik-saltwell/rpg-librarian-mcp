# Asset pack support

Enable meaningful cataloging of map packs, token sets, and audio sets when they contain little text, individual filenames provide weak identification clues, and external searches may return no matches. Folder names are a major source of evidence.

## Scope

In scope:

- `pack` as a second entry type on the [entry table](../entry-table/item.md): a pack table, `file.pack_id`, and a `pack` entry for each pack.
- A new `find-packs` command that identifies packs from catalog evidence, a folder-name search, and an LLM.
- Per-pack enrichment (dtrpg, rpggeek, Google, pooled text analysis; no ISBN).
- Pack support in every MCP tool and CLI command that handles entries, new pack tools, and updates to the `process-batch` and `review-items` skills.
- Placement of pack members by `reorganize`.

Out of scope here:

- Migrating the live catalog, including adopting already-filed products as packs. That is [pack-migration](../pack-migration/item.md).
- Changing how loose (non-pack) files are scanned, enriched or filed.

The exploration behind these decisions is in [idea.md](idea.md). Where this document differs from idea.md, this document is current.

## Expected behavior

**What a pack is.** A set of files with a collective identity (usually the name of their folder or its parent) and no individual identity to look up: map packs, token sets, audio sets, STL sets and similar. A pack is almost always the product itself, not a subfolder of one. Its root is a folder. Every file under the root is a member, including a short description, license or other PDF or text file, but a pack is media-dominated: a folder where documents dominate is never a pack. Automatic duplicates (files `scan` marked as duplicates by hash) are never members.

**Data model.**
- A pack row stores its original scan-time root (a fixed record of why the pack formed, with the evidence and the reasons that formed it), and its own product and disposition.
- `file.pack_id` records membership. A member file has no entry row; the pack has one entry.
- The pack's disposition is the only real one. A member's own `file.disposition` is ignored while `pack_id` is set, and resets to `unfiled` when it leaves the pack. This reverses the entry-table choice that `disposition` lives only on `file`.
- A pack's current root is derived from its members as their deepest common folder, so `reorganize` cannot leave it stale.
- A product has at most one *kept* pack. Keeping a pack under a product that already has a different kept pack is refused, with a message pointing to the merge tool. A superseded earlier version of a pack may share the product (narrowed during planning on 2026-10-02; see [plan.md](plan.md) decision 7).
- A pack with no members left is deleted in the same operation, with its entry and evidence. The product stays. A pack whose members are only missing from the share is kept.

**Finding packs (`find-packs`).** It runs after `scan` and before `enrich`. Scan stays offline.
1. Evidence per folder, read from the catalog: file counts, type mix, numbered-name runs, and sibling folders that look like variants of the same files (img vs png, day vs night, gridded vs gridless).
2. A media-dominance gate drops document-heavy folders and folders already settled.
3. Each remaining candidate folder gets one Google search on its folder name plus its parent's name, cached by normalized query. The hits are corroboration, not proof, and the absence of hits is not evidence against a pack.
4. An LLM walks top-down, one folder level at a time with siblings batched into one call. From the evidence and hits it answers *pack* (descent stops; section subfolders are absorbed), *container* (descend into named children), or *no packs*. Answers for folders without a pack are stored with a fingerprint of the folder's contents so unchanged folders are not asked again.
5. A deterministic check confirms the paths exist, do not overlap, and claim each file at most once. Failures do not become packs.
- **Lossless formation:** a folder becomes a pack only if no existing decision is lost: all its files are unfiled, or all are filed to the same product with the same disposition, and the pack takes that decision. A mixed folder stays as loose files.
- The stored search hits become the pack's `google_search_result`, so `enrich` does not search again.
- Once a pack exists it is never re-judged by the LLM. Its only changes are the manual tools and automatic joining: a file newly created by `scan` under a pack's root joins that pack. A file removed from a pack is an existing file, so it does not rejoin.

**Enrichment.** dtrpg and rpggeek run once per pack. Their query ladder is the root folder name, then its parent's name, then the combined words of the two, then the embedded titles of any member PDFs. File stems and per-file titles are not used. Text analysis pools the sample text of the pack's files, up to a limit. ISBN lookup does not run for packs.

**Tools.**
- `report_entry` on a pack returns a summary: root, member counts by file type, top-level subfolders with counts, a few sample filenames, the pooled evidence, and the current product and disposition. The full file and subfolder listing is only in the new `report-pack` tool.
- New tools: `report-pack`; `add-file-to-pack` (which can also move a file between packs); `remove-file-from-pack`; and `create-pack`, which takes a folder path. Add and remove accept a folder path as well as a file, so one call corrects a whole subfolder. `create-pack` skips the LLM; the pack takes the product and disposition its files already share, and otherwise the call must give them explicitly (this is also how a mixed folder is resolved).
- Every tool that handles entries (reporting, updating, setting the product) handles pack entries. `rename-file` stays file-only and rejects packs.

**Skills.** `process-batch` and `review-items` must work correctly with packs, including the new step order (`scan`, `find-packs`, `enrich`).

## Constraints

- Verification follows the project policy: no new unit tests; behavior-level checks on a copy of the catalog.
- `find-packs` is the only step that spends search and LLM calls for pack formation, and it needs a search key and a model. Offline, detection is less certain.
- The live catalog is not touched by this item; see [pack-migration](../pack-migration/item.md).

## Observable acceptance conditions

- On a test library, `find-packs` finds the packs a person would name from their folders, keeps variant and section subfolders inside one pack, and does not form a pack from a folder of mostly documents.
- A pack of many generically named files can be filed with one `update_product` call, and `reorganize` then moves all its members, keeping their folder structure under the product folder, with the pack's disposition applied.
- A pack with no search matches is still filed and placed from its folder name.
- Enrichment makes one lookup per pack, not per file, and `enrich` does not repeat the Google search that `find-packs` already stored.
- `report_entry` on a pack stays small for a pack of thousands of files, and `report-pack` lists everything.
- Add, remove and create-pack work on files and folders; a pack emptied by these is deleted; a folder correction survives a later `scan`, `find-packs` and `enrich`.
- A second kept pack for an already-packed product is refused.
- `process-batch` and `review-items` complete a run that includes packs.

## Settled decisions and reasons

- **Evidence plus an LLM, top-down, instead of a fixed depth.** `PACK_DEPTH = 3` splits deeper packs and a generic-folder stoplist guesses at meaning. Top-down means cost follows the folders on container chains, not the files.
- **Search only gated, unsettled candidates, and reuse the result.** The live catalog has 4,412 folders (counted read-only), against the 119 requests per-pack asset lookup cost. Serper is paid and rate-limited.
- **The pack owns product and disposition; members inherit.** Members with no entry would otherwise drop out of `compute_placements` (which joins `file` to `entry`) and the pending count. One source of truth keeps placement and pending changes in one place.
- **Original root stored, current root derived.** Keeps the reason a pack formed without a path that `reorganize` can invalidate.
- **One kept pack per product.** A pack is almost always the product, so placement needs no collision handling; "two folders, one product" is merged into one pack. Superseded versions are exempt because they go to `.trash/`.
- **`find-packs` is a separate command.** The evidence is already in the `file` table, so no filesystem walk is needed; scan stays cheap and offline, and the paid steps get their own `--limit` and dry-run and can be inspected before `enrich`.
- **No re-judging of existing packs.** A pack's existence is the pin; no pinned flag or re-judge path.
- **Duplicates are never members.** Duplicate detection is by file hash and already works at file level.
- **Hand-made packs via `create-pack`.** Creating a pack needs a product and disposition up front and is where lossless formation is overridden on purpose.
- **Summary report plus a drill-down tool.** Keeps the agent's context small per pack.

## Unresolved questions

- Table and column design and the Alembic migration, including the new nullable keys on `entry` and `file`.
- The LLM prompt, its answer format, and the evidence summary format.
- The rule for skipping searches on generic folder names (a cost control, not a boundary rule).
- How a validation failure or a mixed folder is presented to the person (command output and the review flow); no new flag type was decided.
- How `reorganize` computes member paths: the direction is the product folder plus the path relative to the pack's root, but the details, and where the stored subpath comes from, are open.
- How automatic joining matches a new file to a pack whose files have since moved from its original root.
- The text analysis pooling limit and which files' samples are pooled first.
- Exact changes to `process-batch`, `review-items`, `describe_schema` and the `query` examples.
- Migration of the live catalog: see [pack-migration](../pack-migration/item.md).

## Quality rubric

Approved qualitative dimensions for judging asset-pack handling:

| Dimension | What it values |
|---|---|
| Pack integrity | Files that belong to one release stay together, including variants and supporting documents, while distinct packs remain separate. |
| Evidence fidelity | Identity and metadata reflect the available folder, document, and media evidence, with uncertainty and conflicting clues represented honestly. |
| Usefulness with sparse evidence | Packs remain discoverable and meaningfully organized when filenames are generic, text is scarce, and external searches return nothing. |
| Processing economy | Lookup cost and human effort stay proportionate to the number of packs and the ambiguity involved, even for packs containing thousands of files. |

These dimensions concern different qualities: pack membership can be correct while its identity is unsupported, and accurate identification can still require excessive processing effort. Evidence fidelity values justified claims; usefulness with sparse evidence values a useful catalog despite incomplete information.
