---
name: review-items
description: Report every catalog item with an open review flag, including its item ID, filename, stored relative path, and the reason it needs review. Use when the user asks to see, list, inspect, or review deferred, needs-review, or flagged RPG-librarian items. This skill is read-only and makes no catalog changes.
---

# Review Items

## Overview

List the human-review queue from the RPG librarian catalog. An item belongs in this
queue only when it has an open `review_flag` row (`resolved_at IS NULL`); do not list
ordinary unfiled files unless they also have an open flag.

## Workflow

1. Confirm that the `rpg-librarian` MCP tools are available. If they are not, stop and
   instruct the user to start Claude from the initialized library project and inspect
   `/mcp`.
2. Call `query` with this read-only SQL:

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

3. Check `truncated`. The MCP query tool returns at most 500 rows. If more rows
   remain, repeat the query using `AND f.id > <last item_id>` and the same ordering
   until every open review flag has been collected.
4. Derive `filename` from the final path component of `stored_path`; preserve
   `stored_path` exactly as returned from the database. Do not infer a filesystem path
   or modify the catalog.
5. Report one Markdown table, ordered by item ID, with exactly these columns:

   | Item ID | Filename | Stored path | Review flag reason |

6. State the total number of items with open review flags. If none are returned, say
   clearly that the review queue is empty.

## Rules

- Never call `update_product`, `rename-file`, `scan`, `enrich`, or `reorganize`.
- Never query `file_text.sample_pages`.
- Do not include resolved review flags, automatic duplicates, or unflagged unfiled files.
- Keep the review reason verbatim apart from Markdown-table escaping.
