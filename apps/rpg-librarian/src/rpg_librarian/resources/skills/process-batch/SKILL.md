---
name: process-batch
description: File or review unfiled files and packs in the rpg-librarian catalog, one folder at a time, using the rpg-librarian MCP tools. Use when the user asks to process the batch or inbox, review needs-review or deferred items, mark junk for removal, or runs /process-batch. This is only the judgment step; scan, find-packs, enrich, and reorganize are run by the user on the command line.
---

# Process a batch

File the catalog's unfiled files and packs into products by recording product type,
product line, and product with the `rpg-librarian` tools. Every tool takes and returns
entry IDs (`entry_id`). An entry is a file or a **pack**: a set of files with one
collective identity (a map pack, token set, audio or STL set) whose files have no
identity of their own. A pack is filed as a whole; its member files never appear on
their own.
Make the judgment calls; deterministic work
(scanning, looking things up, moving files) has already been done, or is done afterwards
by the user.

If the user names a folder or root (for example `/process-batch Games/Fantasy`), work
only on that. Otherwise work through the whole worklist.

If the user explicitly asks to review deferred or needs-review items, use **review
mode** below rather than the normal unflagged worklist. Interpret “remove,” “junk,”
“trash,” or “get rid of this” as a request to set the file's disposition to `discard`.
This records the decision; the later `reorganize` command moves the physical file to
`library/.trash/discarded/` without deleting it permanently.

## Instructions

Use the rpg-librarian tools to file the unfiled files in the catalog. Work a folder at a
time. Product lines and products from earlier batches already exist: search
`list_product_lines` before creating anything, and reuse what's there. If something
cannot be identified, defer it with a review flag rather than guessing.

## Before starting

1. Call `list_product_types`. If the tools are unavailable, stop and tell the user to
   start the agent from the initialized library project and inspect its MCP setup.
2. In review mode, skip the remaining steps in this section and begin at **Review
   mode**. Otherwise, read `list_unfiled` within the requested scope, carrying `root_id`
   and folder boundaries through subsequent calls. For a folder scope, use
   `recursive=true` to check its whole subtree. If there are no unflagged files or
   packs, perform the final backlog check below before stopping. Suggest `scan`,
   `find-packs`, and `enrich` (in that order) only if the scope has nothing unfiled at
   all.
3. Open `report_entry` on one or two entries. If they have no text-analysis hint and every
   evidence block is empty, `enrich` probably has not run: say so, and continue only
   with the user's approval.

## Workflow

1. Learn the vocabulary: `list_product_types`, then `list_product_lines`.
2. Read the scoped worklist with `list_unfiled` and pick a folder.
3. Call `list_unfiled` with that folder (use `recursive` when one product spans
   subfolders) to see its files and packs with their hints. Use `report_entry` for
   anything unclear. A pack is listed in the folder that is its root.
   Check `truncated` and returned counts on every listing. The default limit is 100;
   increase it or inspect subfolders separately before deciding product boundaries.
4. Search `list_product_lines` for the intended line. For an existing line, call
   `report_line` to inspect its products and reuse the exact matching product name.
   Use `report_product` to resolve ambiguous matches before writing.
5. File with `update_product`, one product per call, with at most 500 entry IDs. Split
   larger products across calls using the same product coordinates. Inspect warnings,
   especially similar-name warnings. Correct accidental duplicate assignments by
   re-filing with the existing product name before continuing.
6. Refresh the scoped worklist after successful writes. Repeat until no unflagged
   files remain, then perform the final backlog check below.

## Packs

- File a pack with one `update_product` call on its entry ID: its disposition and
  product apply to every member. `report_entry` on a pack gives a short summary (folder,
  member counts by media type, subfolders, sample names, evidence, text-analysis hint);
  `report-pack` lists every member when the boundary needs checking.
- A pack is usually the product itself. A product holds at most one *kept* pack: if
  two packs are one release (Vol 1 and Vol 2 downloaded separately), merge them with
  `add-to-pack` (pass the other pack's folder) instead of keeping both. A superseded
  earlier version may share the product.
- Correct a boundary by path, as `list_unfiled` and `report-pack` show it:
  `add-to-pack` adds a file or a folder's files (moving them from another pack if
  needed); `remove-from-pack` takes them out, and each comes back as an unfiled file
  with its own entry ID. A pack left with no members is deleted.
- If a folder is clearly one release of assets but its files are listed one by one, make
  it a pack with `create-pack`. If its files are already filed differently, pass the
  pack's decision; the decisions the files give up are listed in the result.
- A pack's evidence comes from its folder names and its short documents (license,
  readme), never from its file names. A pack with no search results can still be filed
  from its folder name.

## Review mode

1. Find open review flags with `query`:

   ```sql
   SELECT rf.entry_id, en.type, COALESCE(f.root_id, p.root_id) AS root_id,
     COALESCE(f.relative_path, p.original_root_path) AS relative_path,
     rf.reason, rf.created_at
   FROM review_flag rf
   JOIN entry en ON en.id = rf.entry_id
   LEFT JOIN file f ON f.id = en.file_id
   LEFT JOIN pack p ON p.id = en.pack_id
   WHERE rf.resolved_at IS NULL
     AND (f.id IS NULL OR f.missing_since IS NULL)
   ORDER BY rf.entry_id
   ```

   For a pack, `relative_path` is the folder it was formed from; `report_entry` shows
   where it is now. Apply any folder or root scope the user supplied. Do not mix
   unflagged items into a review-only request.
2. Call `report_entry` for each item being reviewed so the original reason and current
   evidence are visible before changing it.
3. Follow the user's judgment:
   - For “remove,” “junk,” “trash,” or equivalent, call `update_product` with that
     entry ID, `disposition="discard"`, and a concise `note` recording the reason.
   - For an identified product, call `update_product` with `disposition="keep"` and
     the resolved product coordinates, following the normal vocabulary checks.
   - Use `superseded` only when a retained replacement is known.
   - If the item is still unclear, leave its existing review flag open. Do not open a
     duplicate flag or repeatedly rewrite the same reason.
4. Treat `discard` as a recoverable trash decision, not immediate deletion. Never move
   or delete the physical file during the skill run. `update_product` resolves its
   review flag immediately; a later `reorganize` moves it to `.trash/discarded/`.
5. Re-run the open-review query after the requested decisions and report what remains.

## Judgment

- A product is a set of files that shipped together. The folder path is usually the
  best clue. Search results, ISBN records, and system guesses are hints, not verdicts.
- Evidence on a pack (DriveThruRPG, RPGGeek, Google) comes from searches for its folder
  names and its documents' titles: it may identify the pack, never a single member.
  Google hits on a loose map, token, image, audio, or other non-PDF file come from a
  search for its folder, not for the file.
- Treat one standalone PDF (a core rulebook or adventure) as its own product.
- Treat standalone map packs, music, sound effects, miniatures, and terrain as their
  own product under a functional type, not under a game.
- Distinguish revisions and print variants from distinct game or book editions. Mark a
  file `superseded` only when evidence identifies a retained replacement; age alone is
  insufficient. If the relationship is unclear, defer. Mark clear junk `discard`.
- Automatic duplicates are already handled. Do not try to file them.
- Prefer existing types and lines. A line may already exist under an alias, so search
  first. Create a type only when it is truly needed.
- Fill `product_metadata` only from evidence, never from memory.
- When uncertain, defer with `review_flag` and a reason. When a reviewed item is junk,
  use `discard`; do not leave it review-flagged or confuse it with a duplicate.

## Rules

- Change the catalog only through `update_product` and the pack tools (`create-pack`,
  `add-to-pack`, `remove-from-pack`). Never run `reorganize`, `scan`, `find-packs`, or
  `enrich`, and do not try to read or move files. Nothing moves until the user runs
  `reorganize`.
- Do not query `file_text.sample_pages`.
- If a tool returns an error, read the message and correct the call. Do not repeat the
  same call.

## When finished

Recheck the requested scope with `list_unfiled(include_flagged=true)`; for a folder
scope, include its subtree with `recursive=true`. Handle truncation and use
`report_entry` for flag reasons. Distinguish newly deferred files from the previous
backlog and report remaining unflagged files separately.

Print a concise summary of filed products (saying which were packs), created
lines/types/aliases, pack corrections (created, merged, files removed), items marked
`superseded` or `discard` with their reasons, deferred items, and remaining unflagged
items. Tell the user to review it, then run `rpg-librarian reorganize --dry-run`.
