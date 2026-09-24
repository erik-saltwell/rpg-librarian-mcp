# Plan: per-pack Google lookup for asset media

## Intent

`enrich` currently runs a Google (Serper) search for **every** file (`GoogleSource.wants`
returns `True`). For asset dumps (maps, tokens, art, audio) that means thousands of
paid requests, rate-limited at 5/s, each querying a file name that no search engine
knows. The other sources already skip non-documents (`is_product_document`).

Outcome: for non-document media, one Google request per *pack*, shared by every file in
it. PDFs are unchanged.

## Code inspected

- `apps/rpg-librarian/src/rpg_librarian/enrichment/google.py`: `GoogleSource`.
- `.../enrichment/queries.py`: `FileContext`, `is_product_document`, `google_query`,
  `_words`, `_STORE_ORDER_ID`.
- `.../commands/enrich.py`: `_eligible` / `_run_source` (per file, one row per file,
  `--force` drops rows for files a source no longer `wants`).
- `.../services/reports.py`: `report_file` shows each evidence row's `query` and `results`.
  No change needed.
- `.../resources/skills/process-batch/SKILL.md`: filing guidance.

Measured on the live catalog (read-only): 2,582 non-PDF files in 133 leaf folders and
119 distinct first-3-folder prefixes.

## Design (settled)

- **No schema change.** Each file still gets its own `google_search_result` row, and
  `report_file`, `list_unfiled` hints, and error rows keep working. Files in a pack store
  the same `query` and `results`, so provenance stays honest.
- **Pack** = the file's first `PACK_DEPTH = 3` ancestor folders below the root. This
  matches `library/<type>/<line>/<product>` in the organized library and `Game/Pack/Sub`
  in dumps. The cap stops a pack with hundreds of leaf subfolders from costing hundreds of
  requests.
- **Pack query** = the words of those folders, with DriveThruRPG order ids removed,
  hidden components (`.trash`) dropped, repeated words removed case-insensitively, and the
  result capped at 16 words.
- **Files with no folder** (asset at a root's top level): `wants()` is `False`, because a
  bare file name finds unrelated products. Under `--force`, old rows for them become stale
  and are dropped by the existing mechanism.
- **Memo per run**, keyed by query, holding both successes and non-fatal failures. One
  transient error in a 500-file pack does not cause 500 retries. Fatal errors (auth,
  quota) still stop the source. The memo is reset at the start of each run.
- Cross-run reuse of stored rows is out of scope: a file added later to an already
  looked-up pack costs one request on the next run.

## Phases

### Phase 1: code
- [x] `queries.py`: `pack_query(context)`; update the `is_product_document` rationale.
- [x] `google.py`: `wants` skips asset files with no pack; `fetch` uses `pack_query` for
      non-documents and memoizes per run; update the docstring.
- [x] `enrich.py`: give sources an optional per-run reset hook (`begin_run`).

### Phase 2: docs
- [x] `process-batch` SKILL.md: Google hits on asset files describe the pack, not the file.
- [x] App README: note the per-pack behaviour.

### Phase 3: verification (no unit tests, per project policy)
- [x] `ruff check`, `ruff format --check`, and `ty check`.
- [x] A throwaway script against a **copy** of the catalog in `/tmp`, with Serper
      patched to count calls. Never the live DB, never `--force` live.
      Check: requests ≈ distinct packs; PDFs still per file; stored queries read sensibly;
      a simulated transient failure in a pack costs one request.

## Not done / follow-ups

- Existing asset files already have per-file Google rows and are not re-queried. To
  redo them, delete those rows for non-PDF files, then run `enrich --source google`
  (the user's decision; it deletes data).
- Installed copies of the `process-batch` skill are never overwritten by `init`.

## Verification results (2026-09-24)

- `uv run ruff check apps/rpg-librarian`, `ruff format --check`, `uv run ty check`: all
  pass. The existing suite (`uv run pytest`): 324 passed. `scripts/check_migrations.py`:
  migrations match; no schema change.
- `/tmp/packtest/verify.py` on a backup copy of `~/data/rpg-librarian/catalog.db`, with
  Serper replaced by a counting fake. It deleted the copy's Google rows for non-document
  files and for 20 PDFs, then ran `_run_source` for `google`:
  - Asset files: 2,540 files → **119 requests** (118 packs plus 1 pack made to fail);
    per file it would have been 2,540. The largest pack is
    "vtt packs Index Card RPG ICRPG Core Online Play Assets 1.3", 253 files, 1 request.
  - The injected transient failure: 1 request, 89 error rows (no retry storm). The pack
    is retried on the next run because error rows leave the files eligible.
  - PDFs: still one query each. The copy also held 335 never-searched PDFs; they were
    fetched per file as before.
  - Every query was issued exactly once. Stored queries read sensibly, e.g.
    "games Odyssey of the Dragonlords Maps".
- Not checked: a live Serper run (costs money, and it would have touched the live
  catalog), and the incoming maps/tokens dump, which is not on disk yet.
- Follow-up fix: a failed pack now raises a fresh chained `RuntimeError` for each file
  instead of re-raising the stored exception, whose traceback would grow per file.
  Re-verified on a fresh copy: lint, format, and types pass; the failing pack cost 1
  request and 89 error rows reading `RuntimeError: Serper: RuntimeError('transient')`;
  every query was still issued exactly once.
