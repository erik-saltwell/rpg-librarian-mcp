---
name: review-items
description: Report every catalog item with an open review flag, and every file the last `reorganize` could not move (usually a naming conflict), with options for resolving each blocked file. Use when the user asks to see, list, inspect, or review deferred, needs-review, flagged, blocked, or not-moved RPG-librarian items. Makes no catalog changes unless the user confirms a proposed resolution.
---

# Review Items

## Overview

Report two queues from the RPG librarian catalog:

1. **Review flags**: items with an open `review_flag` row (`resolved_at IS NULL`).
2. **Blocked by reorganize**: files with an `error` row whose `stage` is
   `reorganize`. These are files the last `reorganize` run left where they were, most
   often because another file already has, or also wants, the same destination. These
   rows are a snapshot of the last run; they are replaced every time `reorganize` runs.

Do not list ordinary unfiled files unless they appear in one of these queues. Report
first, change nothing, and act on a blocked file only after the user picks an option.

## Workflow

1. Confirm that the `rpg-librarian` MCP tools are available. If they are not, stop and
   instruct the user to start Claude from the initialized library project and inspect
   `/mcp`.
2. Collect open review flags with `query`:

   ```sql
   SELECT
     f.id AS item_id,
     f.relative_path AS stored_path,
     rf.reason AS review_flag_reason,
     rf.created_at AS deferred_at
   FROM review_flag rf
   JOIN file f ON f.id = rf.file_id
   WHERE rf.resolved_at IS NULL
     AND f.missing_since IS NULL
   ORDER BY f.id
   ```

3. Collect files blocked by the last reorganize with `query`:

   ```sql
   SELECT
     f.id AS item_id,
     f.root_id,
     r.kind AS root_kind,
     f.relative_path AS stored_path,
     f.subpath,
     f.disposition,
     f.product_id,
     f.size_bytes,
     f.sha256,
     e.error_text,
     e.occurred_at
   FROM error e
   JOIN file f ON f.id = e.file_id
   JOIN root r ON r.id = f.root_id
   WHERE e.stage = 'reorganize'
     AND f.missing_since IS NULL
   ORDER BY f.id
   ```

4. For both queries, check `truncated`. The MCP query tool returns at most 500 rows.
   If more rows remain, repeat the query using `AND f.id > <last item_id>` and the same
   ordering until every row has been collected.
5. Derive `filename` from the final path component of `stored_path`; preserve
   `stored_path` exactly as returned from the database. Do not infer a filesystem path.
6. Classify and investigate each blocked file (see **Blocked files** below).
7. Report (see **Report**).

## Blocked files

`error_text` begins with an exception name (for example `RuntimeError: `). Classify by
the rest of the text:

- **Shared destination**: `same destination as file(s) [<ids>]: <dest>`. Two or more
  files the catalog wants at the same place. The listed IDs are the other claimants.
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
  SELECT f.id, f.relative_path, f.subpath, f.disposition, f.product_id, f.size_bytes,
    f.sha256
  FROM file f JOIN root r ON r.id = f.root_id
  WHERE r.kind = 'library'
    AND f.missing_since IS NULL
    AND lower(f.relative_path) = lower('<dest>')
  ```

  If nothing is found, the occupant is not in the catalog; the user should run `scan`
  so it is cataloged, then run this skill again.

Call `report_file` for the blocked file and each other party. Group each conflict once,
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
  ID, `disposition="discard"`, and a `note` naming the kept file. Recommend keeping the
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
- **Leave it**: make no change; it stays blocked on the next run.

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
3. **Proposed resolutions**: when many conflicts share one cause (such as one product's
   sub-folders), present them as a single entry with one proposed rule and a few
   example renames rather than one entry each. Otherwise, one numbered entry per
   conflict group, giving the files
   involved, what the comparison showed, the options with the recommended one first,
   and any question for the user. List stale-scan files together with the instruction
   to run `scan`.
4. Ask the user which options to apply. After applying confirmed choices, report what
   changed and tell the user to run `rpg-librarian reorganize --dry-run`. Resolved
   files stay in the blocked queue until the next `reorganize` run replaces it.

## Rules

- Change the catalog only after the user confirms a specific option, and only with
  `update_product` or `rename-file`. Never call `scan`, `enrich`, or `reorganize`.
- Never query `file_text.sample_pages`.
- Do not include resolved review flags, automatic duplicates, or unflagged unfiled files.
- Keep review reasons and error text verbatim apart from removing the exception name
  and Markdown-table escaping.
- If a tool returns an error, read the message and correct the call. Do not repeat the
  same call.
