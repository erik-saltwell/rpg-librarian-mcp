# `read_pdfs` — spec

Design reached via brainstorm on 2026-07-30. Status: **designed, not yet
implemented.** Referenced from `tools_spec.md` (tool 7).

## Goal

Extract barcode, ISBN/ISSN, sampled page text, and LLM-derived
description/possible-system signal from PDF entries, and persist it as a
new raw, per-source table — following the raw/curated split and
one-table-per-source rules already established in `metadata_plan.md`.

## Model: `PdfContents`

New table, `model/PdfContents.py`, extending `EntryMetadataBase` (same base
as `PdfMetadata` — `entry_id` is the primary key, 0..1 on `Entry`, upserted
in place on re-run, not a separate generated id).

```python
class PdfContents(EntryMetadataBase, table=True):
    barcode: str | None = Field(default=None, nullable=True)
    isbn: str | None = Field(default=None, nullable=True)
    issn: str | None = Field(default=None, nullable=True)
    sample_text: str | None = Field(default=None, nullable=True)  # JSON, see below
    description: str | None = Field(default=None, nullable=True)
    possible_system: str | None = Field(default=None, nullable=True)
```

### Relationship to `PdfMetadata`

`PdfMetadata` currently has `barcode`/`isbn`/`issn`/`sampled_text` columns
that nothing populates — placeholders for this exact feature.
`PdfContents` replaces them:

- Migration drops those four columns from `PdfMetadata`.
- `PdfMetadata` keeps `page_count`, `is_encrypted`, `needs_password`,
  `has_extractable_text`, `likely_scanned` — structural facts about the
  file, unrelated to this feature.
- `PdfExtractor.extract_isbn()`/`extract_issn()` (the generic
  `MetadataExtractor.extract_from_candidates` lookup against the PDF's own
  metadata dict) are no longer called from `PdfExtractor.extract_custom_metadata`
  for `PdfMetadata`. They're still useful — see the ISBN/ISSN resolution
  order below, where they become the final fallback for `PdfContents`.

### `possible_system` is raw signal, not curated

`metadata_plan.md` established `system` as **curation-only** — no raw
table carries it, since raw signal from independent sources is preserved
disagreements-and-all, while `Product.system` is the single reconciled
answer produced by a later curation step. `PdfContents.possible_system` is
this PDF's own LLM-derived guess — one raw source's opinion, same trust
tier as an ISBN barcode match — not written into `Product.system`
directly. It exists purely as future analysis input for whatever curation
step eventually reconciles per-entry hints into `Product.system`. Reuses
`Product.AGNOSTIC` / `Product.UNKNOWN_SYSTEM` as the sentinel values (no
new sentinels).

## Command: `ReadPdfsCommand`

`commands/ReadPdfsCommand.py`, extends `UpdateBaseCommand`
(`commands/UpdateBaseCommand.py`) — same scan/skip/error/commit loop as
`UpdateMetadataCommand`, with a new `ProcessingStage.read_pdfs` member.

### `should_process`

Mirrors `UpdateMetadataCommand.should_process`, plus a media-type filter:

```python
def should_process(self, session: Session, entry: Entry) -> bool:
    if entry.media_type != MediaType.pdf:
        return False
    existing = session.get(PdfContents, entry.id)
    existing_error = session.get(Error, (entry.id, self.processing_stage))
    return existing is None or existing_error is not None
```

Non-PDF entries always return `False` — counted as `skipped`, not an
error. This is the normal case for a directory-scoped call over mixed
media, same as any other command that no-ops on out-of-scope files.

### `process_one`

1. **Encrypted/password-protected PDFs are skipped, not erroed.** If
   `doc.needs_pass` (same check `PdfExtractor.get_has_extractable_text`
   already uses), do not render pages, OCR, or call the LLM — no
   `PdfContents` row is created/updated. Not a failure; a known, expected
   state.
2. **Page selection** (0-indexed page numbers, `n = doc.page_count`):
   - Barcode pages: `{0, 1, n - 1}` as a `set`.
   - Sample-text pages: `set(range(min(5, n))) | set(range(max(0, n - 2), n))`.
   - Using sets means dedup for short documents (1-page, 2-page, 3-page
     docs) falls out of the data structure — no explicit branching per
     page-count bucket.
3. **Rendering:** reuse the `fitz.Document` already open in `PdfExtractor`
   (no `pypdfium2`). Render each sampled page via
   `page.get_pixmap(matrix=fitz.Matrix(scale, scale))` with
   `scale = 300/72` (300 DPI), for both barcode scanning and OCR — one
   constant, not two, as a starting point.
4. **Barcode → ISBN/ISSN:** for each barcode page in page order (e.g. 0,
   1, `n-1`), for each barcode `zxingcpp.read_barcodes(image)` finds on
   that page (in its return order), try in this order:
   1. `isbn.from_ean13(text)`
   2. `issn.from_ean13(text)`
   3. `isbn.validate(text)` (raw decoded text, not EAN-13-decoded)
   4. `issn.validate(text)`

   First success wins: store the raw decoded barcode text in
   `PdfContents.barcode`, the normalized value in `isbn` or `issn`
   accordingly, then stop scanning further pages/barcodes.
5. **Sample text extraction:** for each sample-text page, use direct text
   extraction (`page.get_text("text")`) if it looks extractable (same
   `_page_has_text`-style check `pdf_extractor.py` already uses); otherwise
   OCR that page's rendered image via `pytesseract`. Build
   `PdfContents.sample_text` as JSON:
   ```json
   {"pages": {"1": "...", "2": "...", "140": "...", "141": "..."}}
   ```
   Keyed by actual 1-indexed page number (not list position), so gaps
   between first-N and last-N samples are self-evident.
6. **ISBN/ISSN fallback chain**, only if not already found via barcode:
   1. Barcode match (step 4).
   2. `isbn.extract(sample_text)` / `issn.extract(sample_text)` — regex
      scan + checksum validate over the concatenated sampled text.
   3. `extractor.extract_value(...)` metadata fallback — the PDF's own
      embedded metadata dict, via the existing candidate-name lookup
      (`MetadataExtractor.extract_isbn`/`extract_issn`).
7. **LLM step** (`description`, `possible_system`) — skipped entirely if
   `sample_text` is empty/near-empty across every sampled page (nothing
   for the LLM to reason about; saves the call). Otherwise:
   - Render the prompt from a bundled Jinja template (see below), injecting
     the sampled text JSON and the sentinel values
     (`Product.AGNOSTIC`, `Product.UNKNOWN_SYSTEM`).
   - Call `litellm.completion(model=<from settings>, response_format=PdfLlmJudgment, ...)`
     with a small Pydantic response model:
     ```python
     class PdfLlmJudgment(BaseModel):
         description: str | None
         possible_system: str | None
     ```
   - Store the parsed result directly onto `PdfContents.description` /
     `possible_system`.

### Error handling

- **Tesseract missing:** checked once, up front, before scanning any
  entries (e.g. `pytesseract.get_tesseract_version()` at command
  construction/start) — a missing system binary is an environment
  misconfiguration, not a per-file problem, so it fails the whole command
  immediately rather than erroring every scanned PDF individually.
- **LLM errors, per-entry by default:** caught by `UpdateBaseCommand`'s
  existing try/except, recorded via `_record_error`, that entry counts as
  `errored`, batch continues — same as any other extraction failure.
- **LLM errors, hard-fail exceptions:** `litellm`'s normalized
  `AuthenticationError` and `RateLimitError` are unlikely to resolve
  between entries (a bad key or an exhausted quota fails every subsequent
  call identically) — these propagate out of `process_one` uncaught,
  aborting the whole command run rather than burning through the batch
  producing N identical per-entry errors.
- **Non-PDF entries:** not an error — `should_process` returns `False`,
  counted as `skipped` (see above).
- **Encrypted/password-protected PDFs:** not an error — no row
  created/updated, no error recorded (see step 1 above).

## LLM configuration

No settings/config class exists yet elsewhere in the project — provider
credentials follow the existing convention (`.env` + `os.getenv`, e.g.
`DATABASE_URL` in `alembic/migrations/env.py`), left entirely to
`litellm`'s own standard env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
etc.) — undocumented beyond "set the key your chosen provider needs,"
since litellm already defines those conventions.

The **model choice itself** is different: checked into git (unlike keys),
via a small bundled YAML file, deployed with the package and read relative
to the installed project — not relative to the catalog/library directory
being scanned. Same mechanism already used for `claude.md` and bundled
skills (`db.py`: `resources.files("rpg_librarian_mcp") / "resources" / ...`).

New file: `resources/llm_settings.yaml`, read via `importlib.resources`:
```yaml
model: gpt-4o-mini  # or whatever litellm model string
```

Minimal on purpose — just `model`, no speculative `temperature`/
`max_tokens`/etc. fields until a real need to tune them shows up.

### Prompt templates

Bundled as Jinja templates, same `resources.files()` pattern, e.g.
`resources/prompts/pdf_llm_prompt.jinja` — not inlined as Python strings.

## Naming summary

| Concern | Name |
| --- | --- |
| Model | `model/PdfContents.py` — `PdfContents` |
| Command | `commands/ReadPdfsCommand.py` — `ReadPdfsCommand(UpdateBaseCommand)` |
| Processing stage | `ProcessingStage.read_pdfs` |
| MCP module | `mcp/read_pdfs.py` |
| MCP tool | `read_pdfs(path, ctx, process_recursively=False, force=False)` |
| LLM settings | `resources/llm_settings.yaml` |
| Prompt template | `resources/prompts/pdf_llm_prompt.jinja` |

## New dependencies

- `pytesseract` (pip) + Tesseract OCR system binary (not pip-installable —
  README needs install steps, e.g. `apt install tesseract-ocr` /
  `brew install tesseract`).
- `litellm`.
- `pyyaml` (or whatever YAML lib the project already pulls in transitively
  — check before adding a new direct dependency).
- `jinja2` for prompt templates (check transitive availability first).

`zxing-cpp` and `pypdfium2` are already in `pyproject.toml` — `zxing-cpp`
gets its first real use here; `pypdfium2` was evaluated (Q5) and rejected
in favor of reusing the already-open `fitz.Document` — it remains an
unused dependency after this feature, worth revisiting/removing separately.

## Migration

New alembic migration:
- Create `PdfContents` table.
- Drop `barcode`, `isbn`, `issn`, `sampled_text` columns from `PdfMetadata`.

## Open items / explicitly out of scope

- The curation step that reconciles `PdfContents.possible_system` (and
  other per-source hints) into `Product.system` is not designed here —
  `metadata_plan.md` already flags this as an open item generally.
- OCR/barcode DPI is a single shared constant (300) for both use cases;
  splitting into separate tuned values for OCR vs. barcode was considered
  (Q16) and deferred until real testing shows a need.
- No settings beyond `model` in `llm_settings.yaml` — add fields only when
  an actual tuning need appears.
