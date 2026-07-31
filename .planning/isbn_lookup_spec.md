# `lookup_isbn` — spec

Design reached via brainstorm on 2026-07-30. Status: **complete**,
implemented the same day. Referenced from `tools_spec.md` (tool 10).
Vendors `~/proj/rpg-librarian/src/rpg_librarian/isbn/isbn_lookup.py`
(Google Books → Open Library → Wikidata fallback chain) into this project.

## Implementation notes

Implemented as designed, no deviations. `isbn/lookup.py`'s own
`isbnlib.NotValidISBNError` handling (inside `_google_books_query` and
`lookup()`'s main loop) was kept as a defensive fallback even though
`LookupIsbnCommand` always validates first — harmless, and it means
`isbn_lookup.lookup()` stays safe to call directly (e.g. in tests) without
going through the command layer's pre-validation.

## Goal

Given an ISBN, return bibliographic product data (title, authors,
publisher, year, description) by querying external book-metadata sources,
falling back across providers automatically so the LLM doesn't have to
orchestrate that itself. Reuses the normalized `ProductLookupDetails`
shape already established for `lookup_rpg_geek_product`/`search_dtrpg`
(`commands/ProductLookupResult.py`), with `source="isbn"`.

### Not in scope: ISSN lookup

The tool is named `lookup_isbn` (not "lookup-isbn-or-issn") and only
resolves ISBNs. None of the three vendored providers actually look up
periodicals by ISSN — the original command this was extracted from says so
directly: *"ISSN-only entries are not looked up: isbnlib has no
serial-metadata service, so there is nothing to query for those"*
(`lookup_metadata_from_isbn_command.py:24-30`). An ISSN input is simply
invalid input to `isbn.py`'s existing `validate()` (see below), so it
naturally falls into the "no match" path with no special-casing —
`lookup_isbn("2049-3630")` reliably returns `None`, not an error and not a
lie about having tried a serials database.

### Overlap with the `openlibrary-mcp-server` companion — accepted, not deduped

Open Library is one of `lookup_isbn`'s three fallback providers, and the
companion `openlibrary-mcp-server` (recommended in README, see
`rpg_lookup_spec.md`) also gives the LLM direct Open Library access. Kept
as real, accepted overlap rather than deduped: `lookup_isbn`'s job is "one
ISBN in, best-available metadata out, with the multi-provider
fallback/dedup judgment already encoded" — a fundamentally different shape
of tool than "ad-hoc Open Library search," even though they can hit the
same upstream API for a given book.

## Validation: delegate to the existing `isbn/isbn.py`, not `isbnlib`

The vendored `isbn_lookup.py` uses `isbnlib`'s own validation
(`isbnlib.EAN13`, catching `isbnlib.NotValidISBNError`) internally.
`rpg_librarian_mcp`'s `isbn/isbn.py` already has its own, already-tested
ISBN-10/13 validate/normalize (`python-barcode`-based, used by
`read_pdfs`'s barcode step) — two independent validation implementations
in one package would be redundant.

`lookup_isbn` therefore validates/normalizes via `isbn.py`'s existing
`validate()`/`_normalize()` **first**, before ever calling into the
provider chain. An invalid ISBN (including any ISSN, which fails this
validator) short-circuits straight to `None` -- zero network calls, and
`isbn/lookup.py`'s own vendored code no longer needs its
`isbnlib.NotValidISBNError` handling path (isbnlib is used purely for its
provider queries here: `isbnlib.meta(isbn, service=...)`).

## Return contract: `ProductLookupDetails | None`, real failures propagate

Three distinct outcomes from the vendored `lookup()`, all preserved:

1. **Found** → `ProductLookupDetails`.
2. **Genuine miss** (invalid ISBN, or every provider says "no data") →
   `None`. Not an error — this is a normal, expected outcome for an
   obscure/small-press RPG book that simply isn't in any of these
   databases.
3. **Real failure** (every provider failed for a real reason -- network/
   HTTP error, or Google Books itself unusable) → propagates as a raised
   exception, same "errors propagate, not caught into a structured
   `{"error": ...}` field" convention as `run_readonly_query`/`move`/the
   RPGGeek tools. `GoogleBooksUnavailableError` (quota exhausted, key
   blocked, rate limited) is the main case here — vendored as-is, still
   raised immediately rather than silently falling back, since Open
   Library/Wikidata's hit rate alone is too low to be worth continuing
   without Google Books.

This deliberately diverges from `lookup_rpg_geek_product`'s convention
(raises `ValueError` on not-found) -- there, not-found means "you gave me
a bad id" (caller error); here, a miss is a normal data outcome, not a
caller mistake.

## Response mapping

```python
ProductLookupDetails(
    source="isbn",
    source_id=normalized_isbn,
    title=result.title or "",
    creators=result.authors,
    publisher=result.publisher,
    year_published=int(result.year) if result.year and result.year.isdigit() else None,
    description=result.description,
    # system, thumbnail_url, rating, categories: left at defaults (None/[])
    # -- IsbnLookupResult has no equivalent data, same gap DTRPG results
    # already leave for rating/categories.
)
```

`"isbn"` is a new addition to `ProductLookupResult.Source`
(`Literal["rpggeek", "dtrpg", "isbn"]`).

## Vendored module: `isbn/lookup.py`

Adapted from `rpg_librarian/isbn/isbn_lookup.py`, in the existing `isbn/`
package (not a new top-level package like `rpggeek/`/`dtrpg/` -- `isbn/`
is already this project's home for ISBN-related code, including the
validation this module now delegates to). Kept as-is beyond the validation
change above:

- Provider fallback order: Google Books (only if `GOOGLE_BOOKS_API_KEY` is
  set) → Open Library (`isbnlib` `"openl"` service, plus a second request
  for the work-level description) → Wikidata (`isbnlib` `"wiki"` service).
- Own 2-second minimum-call-interval throttle (`_throttle()`,
  module-level `_last_call_time`), independent of `isbnlib`'s own
  per-host throttling -- kept because catalog-scale runs were the reason
  it was added upstream (anonymous Google Books quota).
- Google Books queried directly via `urllib.request` (not `isbnlib`'s
  "goob" service) so 401/403/429 responses can be told apart from a
  generic HTTP error and raised as `GoogleBooksUnavailableError`.
- `lookup(isbn: str) -> IsbnLookupResult | None` keeps its existing
  signature/behavior; `IsbnLookupResult` (title, authors, publisher, year,
  description) is the vendored module's own native shape, mapped to
  `ProductLookupDetails` by the command layer -- same "vendored client's
  native shape is not reused as-is" precedent as `rpggeek`/`dtrpg`.

## Command: `commands/LookupIsbnCommand.py`

No `CommandProtocol` (same reasoning as the RPGGeek/DTRPG commands -- a
single external lookup, nothing to iterate, no `force`/recursive concept).
Plain sync class (the vendored code is `urllib`/`isbnlib`-based, blocking,
same precedent as `SearchDtrpgCommand`'s sync `requests` usage):

```python
@dataclass
class LookupIsbnCommand:
    lookup_isbn: Callable[[str], IsbnLookupResult | None] = isbn_lookup.lookup

    def run(self, isbn: str) -> ProductLookupDetails | None:
        if not isbn_validate(isbn):
            return None
        normalized = isbn_normalize(isbn)
        result = self.lookup_isbn(normalized)
        if result is None:
            return None
        return ProductLookupDetails(...)  # mapping above
```

`lookup_isbn` as a constructor-injected field (defaulting to the real
`isbn.lookup.lookup` function) mirrors the *upstream* command's own
`lookup_isbn: Callable[[str], IsbnLookupResult | None] = lookup` pattern
(`lookup_metadata_from_isbn_command.py:53`) -- kept because it's exactly
the right shape for testing without network calls, and there's no reason
to invent a different testability mechanism than the one already proven
there.

## MCP registrar: `mcp/isbn.py`

```python
def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="lookup_isbn")
    def lookup_isbn(isbn: str) -> ProductLookupDetails | None:
        """Look up bibliographic metadata for an ISBN (Google Books,
        falling back to Open Library, then Wikidata).

        Returns None if `isbn` is invalid or no provider has data for it --
        not an error. Does not support ISSN (periodical) lookups; an ISSN
        input reliably returns None.
        """
        return LookupIsbnCommand().run(isbn)
```

No lazy client construction needed here (unlike RPGGeek/DTRPG) -- nothing
in `isbn/lookup.py` authenticates or opens a connection at import/construct
time; `GOOGLE_BOOKS_API_KEY` is read per-call inside `_providers()`, so a
missing key just means Google Books is skipped for that call, never a
startup-time failure.

## Naming summary

| Concern | Name |
| --- | --- |
| Response model addition | `commands/ProductLookupResult.py` -- `Source` gains `"isbn"` |
| Vendored lookup module | `isbn/lookup.py` -- `lookup()`, `IsbnLookupResult`, `GoogleBooksUnavailableError` |
| Command | `commands/LookupIsbnCommand.py` -- `LookupIsbnCommand` |
| MCP module | `mcp/isbn.py` |
| MCP tool | `lookup_isbn(isbn: str) -> ProductLookupDetails \| None` |

## New dependency

- `isbnlib>=3.10.14` -- used only for its provider-query functions
  (`isbnlib.meta(isbn, service=...)`) and the `isbnlib.dev` error types
  (`DataNotFoundAtServiceError`, `ISBNLibHTTPError`); its own ISBN
  validation is bypassed per the "Validation" section above.

## Config / environment

New optional env var, documented in both `.env.example` **and README's
install section** (same pattern as `RPGGEEK_BEARER_TOKEN`/`DTRPG_API_KEY`
-- do not forget the README, per explicit instruction):

- `GOOGLE_BOOKS_API_KEY` -- optional. Unset: `lookup_isbn` still works,
  falling back to Open Library then Wikidata (isbnlib's anonymous Google
  Books quota is not used at all -- `_providers()` only adds the Google
  Books provider when this key is present). Set: much higher quota, and
  Google Books is the only provider of the three that returns a
  description in the same response.

## Open items / explicitly out of scope

- **No ISSN metadata source** -- see "Not in scope" above. If a real need
  for periodical lookups ever appears, that's a separate tool/spec, not an
  extension of this one.
- **Product-write tool** -- same deferral as `rpg_lookup_spec.md`;
  `lookup_isbn`'s output is read-only, consumed by whatever future tool
  writes `Product.identification_method` (this would presumably add an
  `isbn_match` member alongside the existing `isbn_match` value already in
  `IdentificationMethod` -- worth double-checking that enum member's
  current meaning lines up with this tool's output before that future work
  starts).
- **No caching** -- repeated `lookup_isbn` calls for the same ISBN within
  one session re-query providers each time, same as upstream. Not added
  speculatively.
