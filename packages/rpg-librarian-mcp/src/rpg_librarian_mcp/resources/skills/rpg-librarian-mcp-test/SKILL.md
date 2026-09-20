---
name: rpg-librarian-mcp-test
description: Exercise the tools/functions exposed by the rpg-librarian MCP to test it for bugs and defects. Use when the user asks to test, exercise, or find bugs in the rpg-librarian MCP.
---

# RPG Librarian MCP Test

## Goal

Use the functions in the rpg-librarian MCP to test the MCP for bugs/defects.
The goal is to exercise the various tools exposed by the MCP.

## Scope

If the user does not specify which tools/functions to test, assume you must
exercise all of them.

## Workflow

1. If this is a new directory with no catalog database yet, call
   `update-catalog` first before exercising any other tool.
2. Exercise each relevant tool/function of the MCP, trying normal cases and
   edge cases (bad input, missing arguments, empty results, etc.).
3. Do not stop when you find a bug — keep testing until you have exercised
   all relevant tools/functions of the MCP.

## Known operating expectations

These behaviors are intentional, not defects — do not report them as bugs:

- The catalog requires every file to be at least two levels deep under the
  library root (a parent folder and a grandparent folder). A file placed
  directly in the library root is out of scope by design — expect a clean
  per-file error (e.g. "... is too shallow to be cataloged (need at least a
  parent and grandparent folder)"), not successful cataloging. This applies
  to `update_catalog` and `move` alike.
- `read_pdfs` requires working LLM credentials (e.g. `OPENAI_API_KEY`) to
  produce any persisted signal for a PDF whose sampled text is non-empty —
  the LLM call judges the PDF's description/possible system. In an
  environment with no LLM credentials configured, expect an `errored` result
  and an `Error` row for such PDFs; this is not a defect. (Non-LLM signal —
  barcode/ISBN/ISSN/sample-text — is still persisted even when the LLM step
  fails, so a `PdfContents` row with those fields populated and
  `description`/`possible_system` left `null` is the correct outcome, not a
  partial-failure bug.)
- `update_catalog`, run in directory mode (recursive or not) directly on the
  library root itself, does not scan or report on files sitting loose in
  that root directory -- they're excluded from `scanned` entirely, with no
  error recorded. This differs from scanning any other directory (e.g.
  `books/`), where a loose too-shallow file inside it *is* scanned and
  correctly errored as "too shallow". Calling `update_catalog` directly on
  the loose root-level file's own path still correctly errors it as
  too-shallow. Do not report the root-directory-scan gap as a bug.
- `move` and `remove` both leave behind empty source directories after
  relocating/removing the last file in them (e.g. moving the only file out
  of `DriveThruRPG/Publisher/Product/` leaves `Publisher/` and `Product/` on
  disk, empty). Neither tool cleans up emptied parent directories. This is
  consistent between the two tools and is not a bug in either one — do not
  report it.
- `update_metadata` on a `.lys` mesh file completes with `succeeded` and
  creates a `file_metadata` row, but does not create a `mesh_metadata` row
  (no bounding box / surface area / unit) and records no `Error` row
  explaining the gap. Only `.stl` mesh geometry extraction is supported
  today; `.lys` files are correctly typed `media_type: "mesh"` but get no
  geometry metadata. Do not report the missing `mesh_metadata` for `.lys`
  files as a bug.

## Reporting bugs

When you find a bug, write a description of the bug and how to reproduce it
to a file called `.errors.md` at the root of the current working directory.

- Use Markdown formatting.
- Append new findings rather than overwriting prior ones, unless the user
  asks you to start fresh.
- For each bug include: the tool/function called, the input used, the
  expected behavior, the actual behavior, and steps to reproduce.

## End State
The user maintains a backup of this directory, so persistent changes are allowed.
You do not need to rollback changes when you are done.
