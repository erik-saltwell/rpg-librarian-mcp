---
name: rpg-librarian-mcp-organize
description: Run a full organizing pass over a directory of the RPG library -- catalog, identify, classify, and file products into the library's target scheme. Use when the user asks to organize, sort, catalog, clean up, or file a directory/drive/folder into the library, or to keep going/continue an organizing pass already in progress.
---

# RPG Librarian MCP Organize

This skill is the *process* for running an organizing pass: how to move
through a directory in disciplined batches, when to trust an
identification vs. flag it for a human, and how to report progress on a
job that can span thousands of files and multiple sessions.

It is deliberately not the *policy* for what goes where -- that's
`CLAUDE.md`'s "Target organization scheme" and "Typical workflow"
sections, in the library root. Always re-read `CLAUDE.md` before starting
in case the user has edited the scheme for this library; if this skill
and `CLAUDE.md` ever disagree, `CLAUDE.md` wins.

## Scope

If the user names a path, work within it. If they don't, ask which
directory to organize rather than defaulting to the whole library root --
a full-library pass is a long-running commitment worth confirming.

If the content is coming from outside the library (a friend's drive, an
old backup, a new download folder), run `ingest_external_source` first so
only genuinely new files get staged into `_inbox/<name>/`, then treat that
staged copy as the path to organize.

If any site lookups you'll need (RPGGeek, DriveThruRPG, etc.) require a
login, run the `rpg-librarian-mcp-authenticate` skill first rather than
letting the pass stall on an access-denied error partway through.

## Workflow

Work in batches sized to one product-cluster or one subdirectory at a
time -- never try to identify an entire multi-thousand-file directory in
a single sweep. A batch this size keeps each round of tool calls
reviewable and keeps a crash or interruption from losing much work.

1. `update_catalog` on the target path to bring it up to date with disk.
2. `summarize_directories` / `list_directory_entries` to see what's
   cataloged and pick the next unidentified batch to work through.
3. For each product in the batch, identify it using the cheapest source
   likely to be *correct* first, falling through only as needed:
   1. `lookup_isbn` (if a barcode/ISBN is visible or already extracted)
   2. `search_rpg_geek` + `lookup_rpg_geek_product`
   3. `search_dtrpg`
   4. `read_pdfs` (sample text/description to help identify a PDF whose
      title/publisher aren't obvious from its filename)
   5. Manual judgment from filename/folder/context, only once the above
      are exhausted or clearly inapplicable (e.g. a non-PDF media type).
4. Don't guess past your actual confidence. If nothing above produces an
   identification you'd stand behind, call `flag_for_review` with a
   specific, useful reason and move on to the next product -- do not stall
   the pass on one ambiguous item, and do not silently invent a plausible-
   sounding title/publisher to keep moving.
5. `update_product` to link the identified files to a product record.
6. `classify_content_role` for each system-specific product (skipped
   automatically for system-agnostic content).
7. `move` to file the product into the scheme described in `CLAUDE.md`.
8. Repeat from step 2 with the next batch until the target path is fully
   processed, or you've reached a natural stopping point (see below).

## Progress and stopping points

This is long-running work -- report progress rather than going silent for
an extended stretch:

- After each batch, give a short running tally (processed / identified /
  flagged for review / errored so far), not a play-by-play of every tool
  call.
- Check `list_errors` periodically; note anything that needs the user's
  attention, but don't let a single file's error stop the pass -- keep
  going and summarize errors at the end.
- It's fine to stop and resume across sessions. A later run of this skill
  on the same path just picks up wherever `summarize_directories` shows
  work remaining -- there's no separate checkpoint to maintain.
- At the end of a pass (or when told to stop), give a final summary: totals
  cataloged/identified/flagged/moved/errored, and call out anything flagged
  for review so the user knows what needs their judgment.

## What this skill does not do

- It does not decide the organization scheme -- that's `CLAUDE.md`.
- It does not resolve review flags -- that's the user's call, via
  `resolve_review_flag`, once they've looked at what got flagged.
- It does not deduplicate the library -- run `find_duplicates` separately
  if that's the goal.
