---
name: review-items
description: Report every catalog item with an open review flag, every file or pack the last `reorganize` could not move (usually a naming conflict), and every folder `find-packs` saw as a pack but left as loose files, with options for resolving each. Use when the user asks to see, list, inspect, or review deferred, needs-review, flagged, blocked, or not-moved RPG-librarian items. Makes no catalog changes unless the user confirms a proposed resolution.
---

# Review Items

## Overview

Report three queues from the RPG librarian catalog:

1. **Review flags**: items with an open `review_flag` row (`resolved_at IS NULL`).
2. **Blocked by reorganize**: items with an `error` row whose `stage` is
   `reorganize`. These are files the last `reorganize` run left where they were, most
   often because another file already has, or also wants, the same destination. These
   rows are a snapshot of the last run; they are replaced every time `reorganize` runs.
   A pack has one row summarizing all its members that could not move.
3. **Folders left as loose files**: folders `find-packs` judged to be packs but did not
   form (`folder_judgment.outcome` `mixed`: forming it would lose a decision; `invalid`:
   the answer failed validation; `error`: the search or model call failed and will be
   retried).

Every item ID is an entry ID (`entry.id`), the ID the MCP tools take. An entry is a file
(`entry.file_id`) or a pack (`entry.pack_id`): a set of files with one collective
identity, whose members have no entry of their own. Do not list ordinary unfiled items
unless they appear in one of these queues. Report first, change nothing, and act only
after the user picks an option.

## Workflow

1. Confirm that the `rpg-librarian` MCP tools are available. If they are not, stop and
   instruct the user to start Claude from the initialized library project and inspect
   `/mcp`.
2. Collect open review flags with `query`:

   ```sql
   SELECT
     en.id AS item_id,
     en.type AS item_type,
     COALESCE(f.relative_path, p.original_root_path) AS stored_path,
     rf.reason AS review_flag_reason,
     rf.created_at AS deferred_at
   FROM review_flag rf
   JOIN entry en ON en.id = rf.entry_id
   LEFT JOIN file f ON f.id = en.file_id
   LEFT JOIN pack p ON p.id = en.pack_id
   WHERE rf.resolved_at IS NULL
     AND (f.id IS NULL OR f.missing_since IS NULL)
   ORDER BY en.id
   ```

   For a pack, `stored_path` is the folder it was formed from; `report_entry` gives its
   current folder.

3. Collect files blocked by the last reorganize with `query`:

   ```sql
   SELECT
     en.id AS item_id,
     en.type AS item_type,
     COALESCE(f.root_id, p.root_id) AS root_id,
     r.kind AS root_kind,
     COALESCE(f.relative_path, p.original_root_path) AS stored_path,
     f.subpath,
     COALESCE(f.disposition, p.disposition) AS disposition,
     en.product_id,
     f.size_bytes,
     f.sha256,
     e.error_text,
     e.occurred_at
   FROM error e
   JOIN entry en ON en.id = e.entry_id
   LEFT JOIN file f ON f.id = en.file_id
   LEFT JOIN pack p ON p.id = en.pack_id
   JOIN root r ON r.id = COALESCE(f.root_id, p.root_id)
   WHERE e.stage = 'reorganize'
     AND (f.id IS NULL OR f.missing_since IS NULL)
   ORDER BY en.id
   ```

   A pack row's `error_text` reads `N member file(s) of this pack could not be moved:
   <path>: <reason>; ...` (the first few members, then `and N more`). Classify each
   listed member's reason as below, and call `report-pack` for the member paths.

4. Collect the folders `find-packs` left as loose files with `query`:

   ```sql
   SELECT
     j.root_id,
     r.label AS root_label,
     j.folder,
     j.outcome,
     j.reason,
     j.details,
     j.judged_at
   FROM folder_judgment j
   JOIN root r ON r.id = j.root_id
   WHERE j.outcome IN ('mixed', 'invalid', 'error')
   ORDER BY j.root_id, j.folder
   ```

5. For every query, check `truncated`. The MCP query tool returns at most 500 rows.
   If more rows remain, repeat the query using `AND en.id > <last item_id>` and the same
   ordering until every row has been collected.
6. Derive `filename` from the final path component of `stored_path`; preserve
   `stored_path` exactly as returned from the database. Do not infer a filesystem path.
7. Classify and investigate each blocked file (see **Blocked files** below) and each
   folder left as loose files (see **Folders left as loose files**).
8. Report (see **Report**).

## Blocked files

`error_text` begins with an exception name (for example `RuntimeError: `). Classify by
the rest of the text:

- **Shared destination**: `same destination as entry(ies) [<ids>]: <dest>`. Two or
  more files the catalog wants at the same place. The listed entry IDs are the other
  claimants. Rows from before the entry table say `file(s)`; their IDs are the same
  entry IDs.
- **Occupied destination**: `something already exists at the destination: <dest>`.
  Something is already at `<dest>` (relative to the library root). Older runs omit the
  `: <dest>` part; then treat the occupant as unknown and suggest re-running
  `rpg-librarian reorganize --dry-run` to see it.
- **Chain**: `its destination is held by a file that cannot move`. Another blocked file
  holds the destination; it usually clears once that file is resolved.
- **Stale scan**: `the file is not at its recorded path` or `the file changed since
  the last scan`. Not a conflict: the user should run `rpg-librarian scan` and then
  `reorganize` again. Offer no other options.

For each naming conflict (shared or occupied destination), find the other party:

- Shared: the other claimants are the listed IDs.
- Occupied: look for a cataloged file at that path in the library root, comparing
  case-insensitively (the share usually is):

  ```sql
  SELECT COALESCE(en.id, pe.id) AS item_id,
    CASE WHEN f.pack_id IS NULL THEN 'file' ELSE 'pack member' END AS kind,
    f.relative_path, f.subpath,
    COALESCE(p.disposition, f.disposition) AS disposition,
    COALESCE(en.product_id, pe.product_id) AS product_id,
    f.size_bytes, f.sha256
  FROM file f
  LEFT JOIN entry en ON en.file_id = f.id
  LEFT JOIN pack p ON p.id = f.pack_id
  LEFT JOIN entry pe ON pe.pack_id = p.id
  JOIN root r ON r.id = f.root_id
  WHERE r.kind = 'library'
    AND f.missing_since IS NULL
    AND lower(f.relative_path) = lower('<dest>')
  ```

  A `pack member` occupant is identified by its pack's entry ID.

  If nothing is found, the occupant is not in the catalog; the user should run `scan`
  so it is cataloged, then run this skill again.

Call `report_entry` for the blocked file and each other party. Group each conflict once,
listing all its files, rather than repeating it for every member. Compare:

- **Same content** (equal, non-null `sha256`): the files are identical copies.
- **Same product** (equal `product_id`): `reorganize` keeps a product's source
  sub-folders below the deepest folder its files share in one source, but files of the
  same product can still meet: from two different sources, or flattened because that
  shared folder also held other products' files. Compare each file's stored
  `file.subpath` (NULL until its product first moves) and source folder; the
  differing sub-folder is usually the best distinguishing name.
- **Different products**: often two single-file products in one line whose files share
  a generic name (for example `Map.pdf`). A product with one kept file goes directly
  into its line folder, so such names collide there.

Then offer the options that fit, recommending one with a short reason:

- **Discard the copy** (same content only): `update_product` with the redundant file's
  entry ID, `disposition="discard"`, and a `note` naming the kept file. Recommend keeping the
  file that is already in the library.
- **Rename one file**: propose a specific new filename for the blocked file (or the
  other party) that tells them apart, based on evidence such as its product, source
  folder, edition, or page count. Keep the extension. For same-product sub-folder
  collisions, propose appending the sub-folder, for example
  `barbarian (No magic items).pdf`, and rename every colliding variant in that
  product the same way so the names stay consistent. Apply with `rename-file`, one
  call per file. A file whose product has already moved is renamed in the catalog only
  (`on_disk` is false); either way the next `reorganize` puts it in place.
- **Mark superseded**: only when evidence shows one is an older edition of the other.
  `update_product` with `disposition="superseded"` and the retained product's
  coordinates.
- **Re-file**: if the evidence shows the blocked file belongs to a different product,
  `update_product` with `disposition="keep"` and the correct coordinates, following the
  vocabulary checks in the `process-batch` skill.
- **Take a member out of its pack** (pack members only): a pack member has no entry of
  its own, so it cannot be renamed or filed alone. `remove-from-pack` with the pack's
  entry ID and the member's path gives it its own entry ID (unfiled); then rename,
  discard, or file it like any other file. Recommend this only when the member really
  is different from the rest of the pack.
- **Leave it**: make no change; it stays blocked on the next run.

## Folders left as loose files

- **Mixed** (`its files are filed differently; forming it would lose a decision`, or
  `its files' product already has a kept pack`): `details.decisions` lists the
  `disposition:product id` pairs. Offer to make it a pack with `create-pack` and an
  explicit decision (the decisions given up are reported), to merge it into the
  product's existing kept pack with `add-to-pack`, or to leave its files loose.
- **Invalid** (`it overlaps an existing pack`, `no file below it can be a member`, …):
  usually an earlier correction already covers it. Call `report-pack` on any overlapping
  pack; offer `create-pack` or `add-to-pack` only if the evidence shows one release.
- **Error**: the search or model call failed; it is retried by the next `find-packs`
  run. Report it; offer nothing else.

Say what you need from the user when the evidence cannot decide, for example which of
two different files to keep or what to call one.

## Report

1. **Review flags**: one Markdown table, ordered by item ID, with exactly these columns:

   | Item ID | Filename | Stored path | Review flag reason |

   State the total. If there are none, say clearly that the review queue is empty.
2. **Blocked by reorganize**: one Markdown table, ordered by item ID:

   | Item ID | Filename | Stored path | Blocked because | Conflicts with |

   `Blocked because` is the classification plus the destination. `Conflicts with` lists
   the other party's item ID and path, `uncataloged`, or `—`. State the total. If
   there are none, say that the last `reorganize` moved everything it attempted.
3. **Folders left as loose files**: one Markdown table ordered by root and folder:

   | Root | Folder | Outcome | Reason |

   State the total, or say that `find-packs` formed every pack it found.
4. **Proposed resolutions**: when many conflicts share one cause (such as one product's
   sub-folders), present them as a single entry with one proposed rule and a few
   example renames rather than one entry each. Otherwise, one numbered entry per
   conflict group, giving the files
   involved, what the comparison showed, the options with the recommended one first,
   and any question for the user. List stale-scan files together with the instruction
   to run `scan`.
5. Ask the user which options to apply. After applying confirmed choices, report what
   changed and tell the user to run `rpg-librarian reorganize --dry-run`. Resolved
   files stay in the blocked queue until the next `reorganize` run replaces it.

## Rules

- Change the catalog only after the user confirms a specific option, and only with
  `update_product`, `rename-file`, `create-pack`, `add-to-pack`, or
  `remove-from-pack`. Never call `scan`, `find-packs`, `enrich`, or `reorganize`.
- Never query `file_text.sample_pages`.
- Do not include resolved review flags, automatic duplicates, or unflagged unfiled files.
- Keep review reasons and error text verbatim apart from removing the exception name
  and Markdown-table escaping.
- If a tool returns an error, read the message and correct the call. Do not repeat the
  same call.
