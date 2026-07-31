# RPG product lookup tools — spec

Design reached via brainstorm on 2026-07-30. Status: **complete**,
implemented the same day. Referenced from `tools_spec.md` (tools 8–9).

## Implementation notes (deviations from the design above)

- `RpgGeekClient.find_candidates` gained a `max_values` parameter directly
  (rather than slicing in the command layer) — the spec's Q15 decision to
  expose `max_values` on `search_rpg_geek` is most naturally implemented
  where the existing `[:5]` slice already lived, so this is the one
  intentional line of drift from the "vendored essentially as-is" DTRPG
  client's treatment; RPGGeek's client got this one small, spec-driven
  edit beyond the `structlog` → `logging` conversion.
- `DriveThruRPGClient._get`'s return type was corrected from `dict` to
  `list[dict]` to match its two actual call sites (`order_products`,
  `products` — both list-returning; `auth_key` is fetched directly in
  `_authenticate`, bypassing `_get`). Upstream's annotation was simply
  wrong; `ty` (this project's type checker, not run against the standalone
  `dtrpg_mcp` project) caught it immediately.
- `DriveThruRPGClient.__init__` drops the vendored `load_dotenv()` call —
  this project already loads `.env` once at server startup
  (`catalog.load_env()`, `server.py`), so a second per-module dotenv load
  would be redundant and inconsistent with every other client/tool here.
- RPGGeek's multi-valued `systems`/`publishers` lists collapse to a single
  `ProductLookupDetails.system`/`.publisher` string via `"; ".join(...)`
  (empty → `None`) in `LookupRpgGeekProductCommand` — `ProductLookupDetails`
  models one system/publisher per source per the spec above, and RPGGeek is
  the only source that can return more than one.

## Goal

Give the LLM a way to search external RPG-product sources (RPGGeek,
DriveThruRPG) and pull back structured candidate/detail data it can reason
about — e.g. when trying to identify what a cataloged file actually is.
**Read-only for this batch**: nothing here writes to `Product`. A future
`identify_product`-style tool will consume this data and write
`Product.identification_method` — out of scope here (see "Open items").

Source code is adapted from two existing, working sibling projects
(`~/proj/rpggeek-mcp`, `~/proj/dtrpg_mcp`) — **vendored** (copied and
adapted in place) rather than pulled in as a dependency, so this project
owns and evolves the code going forward rather than tracking upstream.

## Tools

| Tool | Wraps | Source |
| --- | --- | --- |
| `search_rpg_geek(name, isbn, max_values=5)` | `find_candidates` | RPGGeek `xmlapi2` |
| `lookup_rpg_geek_product(rpggeek_id)` | `get_product_details` | RPGGeek `xmlapi2` |
| `search_dtrpg(query, scope="catalog", max_values=10)` | `search_library`/`search_products` | DriveThruRPG `vBeta` API |

### No `lookup_dtrpg_product`

Considered and dropped. DriveThruRPG's single-item `products/{id}` endpoint
returns 403 regardless of auth (per `dtrpg_mcp/client.py`'s own module
docstring — the `applicationKey` used is scoped to search endpoints only)
and both of DTRPG's search calls already return full product detail per
hit (title, description, publisher, authors, game system) — there is no
API to build a separate lookup tool around, and `search_dtrpg` returning
full details per result already covers the need.

## Response models: `commands/ProductLookupResult.py`

New shared file, same precedent as `commands/ProcessingError.py` (a small
result type living in `commands/`, not `model/` — these are transient API
results, not persisted `SQLModel` tables like everything currently in
`model/`).

```python
class ProductCandidate(BaseModel):
    source: Literal["rpggeek", "dtrpg"]
    source_id: str
    title: str
    year_published: int | None = None


class ProductLookupDetails(BaseModel):
    source: Literal["rpggeek", "dtrpg"]
    source_id: str
    title: str
    year_published: int | None = None
    description: str | None = None
    publisher: str | None = None
    system: str | None = None
    creators: list[str] = []
    thumbnail_url: str | None = None
    rating: float | None = None       # RPGGeek only; None from DTRPG
    categories: list[str] = []        # RPGGeek only; [] from DTRPG
```

- `search_rpg_geek` → `list[ProductCandidate]` (RPGGeek's real API is
  two-step: cheap search, separate detail fetch).
- `lookup_rpg_geek_product` → `ProductLookupDetails`.
- `search_dtrpg` → `list[ProductLookupDetails]` directly — DTRPG's search
  gives full details for free per hit; discarding that down to the
  lightweight `ProductCandidate` shape for uniformity would be a pure data
  loss for no benefit (see brainstorm Q8).
- `source` values are plain source tags (`"rpggeek"`/`"dtrpg"`), **not**
  `IdentificationMethod`'s values (`"rpggeek_match"`/`"drivethru_match"`).
  These are different concepts: `IdentificationMethod` records a decision
  already made about a `Product`; `source` just says which API answered a
  search. The future write-tool maps one to the other trivially.
- `creators` is a generic field — RPGGeek's `designers` and DTRPG's
  `authors` both land here as-is, source-agnostic. **Known gap, not
  resolved here:** `Product` (`model/Product.py`) has an `artists` field
  but no `authors`/`designers`/`creators` field, so neither source's
  creator list maps cleanly onto anything on `Product` today. Left for
  whichever future change adds the write-tool.
- `source_id` is `str` even though RPGGeek's native id is numeric — DTRPG's
  `product_id` is also numeric, but keeping both as opaque strings avoids
  the lookup tool's caller needing to know or care about per-source id
  types.

## Vendored client packages

Two new top-level packages, following "implementations live in their own
package, `commands/` holds command classes, `mcp/` holds thin registrars":

- `rpg_librarian_mcp/rpggeek/client.py` — adapted from
  `rpggeek-mcp/src/rpggeek_mcp/mcp/rpggeek_client.py` +
  `mcp/models.py`. `structlog` calls converted to stdlib `logging` (this
  project's convention, per `server.py`) — the only functional change from
  upstream; XML parsing, rate-limit sleep (1s via `asyncio.sleep` before
  each call), and the `/search` + `/thing` endpoint logic are unchanged.
- `rpg_librarian_mcp/dtrpg/client.py` — adapted from
  `dtrpg_mcp/src/dtrpg_mcp/client.py` essentially as-is (already uses
  stdlib-friendly patterns, no `structlog`). Auth-token refresh-on-401,
  concurrent library-page fetching, and the `search_products`/
  `search_library` split are unchanged.

Both clients' own response dataclasses/pydantic models (`Candidate`,
upstream `ProductDetails` ×2) are **not** reused as-is — the commands layer
maps them into this project's normalized `ProductCandidate`/
`ProductLookupDetails` (see above).

### Client construction: lazy, not eager

`DriveThruRPGClient.__init__` does `os.environ["DTRPG_API_KEY"]` (raises if
unset) and authenticates over the network immediately; `RpgGeekClient`
warns but proceeds if `RPGGEEK_BEARER_TOKEN` is unset. If either were
constructed at `create_server()` time (`server.py`, alongside the other
registrars), a missing/invalid key would crash the **entire**
`rpg-librarian-mcp` server — including every catalog/file tool that has
nothing to do with either external API.

Both clients are therefore built lazily, one instance per process,
constructed on first tool call — same pattern `dtrpg_mcp/server.py` already
uses for itself (`@lru_cache(maxsize=1)` factory function). A missing key
only breaks that specific tool's calls, not server startup.

## Commands — no `CommandProtocol`

`CommandProtocol` (`process(starting_path, process_recursively, force, ctx)
-> ResultType`) is shaped for scanning `Entry` rows already in the catalog.
These three commands take no `path`, iterate nothing, and have no
`force`/recursive concept — they're single external-API calls translated
into this project's response shapes. Plain classes, one per tool, in
`commands/`:

```python
# commands/SearchRpgGeekCommand.py
class SearchRpgGeekCommand:
    def __init__(self, client: RpgGeekClient) -> None: ...
    async def run(self, name: str | None, isbn: str | None, max_values: int = 5) -> list[ProductCandidate]: ...

# commands/LookupRpgGeekProductCommand.py
class LookupRpgGeekProductCommand:
    def __init__(self, client: RpgGeekClient) -> None: ...
    async def run(self, rpggeek_id: int) -> ProductLookupDetails: ...

# commands/SearchDtrpgCommand.py
class SearchDtrpgCommand:
    def __init__(self, client: DriveThruRPGClient) -> None: ...
    def run(self, query: str, scope: Literal["library", "catalog"] = "catalog", max_values: int = 10) -> list[ProductLookupDetails]: ...
```

- RPGGeek commands are `async def run` (matching `RpgGeekClient`'s
  `httpx.AsyncClient`); the DTRPG command stays plain sync (matching
  `DriveThruRPGClient`'s `requests` usage) — no forced uniformity. FastMCP
  already supports both sync and async tools side by side (`move` is sync,
  `update_metadata` is async).
- Each command's job is: call the client, map the client's native
  dataclass/model onto `ProductCandidate`/`ProductLookupDetails`, return.
  No DB access, no `session_scope` — nothing here touches the catalog.
- Not found (`lookup_rpg_geek_product` with a bad id) raises `ValueError`,
  propagating as a normal tool error — same convention as
  `run_readonly_query`/`move` ("errors propagate, not caught into a
  structured `{"error": ...}` field").

## MCP registrars

- `mcp/rpg_geek.py` — registers `search_rpg_geek` and
  `lookup_rpg_geek_product`, both backed by one lazily-constructed
  `RpgGeekClient` shared between the two commands.
- `mcp/dtrpg.py` — registers `search_dtrpg`, backed by one
  lazily-constructed `DriveThruRPGClient`.
- Both added to `REGISTRARS` in `mcp/__init__.py`, same one-line-per-module
  pattern as every existing tool.

```python
@mcp.tool
async def search_rpg_geek(
    name: str | None = None, isbn: str | None = None, max_values: int = 5
) -> list[ProductCandidate]:
    """Search RPGGeek for candidate products by name and/or ISBN."""

@mcp.tool
async def lookup_rpg_geek_product(rpggeek_id: int) -> ProductLookupDetails:
    """Fetch full product details for an RPGGeek item by its numeric id."""

@mcp.tool
def search_dtrpg(
    query: str, scope: Literal["library", "catalog"] = "catalog", max_values: int = 10
) -> list[ProductLookupDetails]:
    """Search DriveThruRPG (the caller's purchased library, or the whole
    catalog) for products matching `query`, returning full details."""
```

- `search_dtrpg`'s `scope` defaults to `"catalog"` (search all of
  DriveThruRPG) — the common case is looking up a product the caller may
  not already own, not confirming something already in their library.
- `search_rpg_geek` keeps `name`/`isbn` as two separate optional params
  (isbn takes priority if both given, mirroring `find_candidates`'
  existing behavior) rather than collapsing to one `query` string — a real
  behavioral distinction (ISBN search is exact-ish, name search is fuzzy),
  not just a naming choice.

## Naming summary

| Concern | Name |
| --- | --- |
| Response models | `commands/ProductLookupResult.py` — `ProductCandidate`, `ProductLookupDetails` |
| RPGGeek client | `rpggeek/client.py` — `RpgGeekClient` |
| DTRPG client | `dtrpg/client.py` — `DriveThruRPGClient` |
| Commands | `commands/SearchRpgGeekCommand.py`, `commands/LookupRpgGeekProductCommand.py`, `commands/SearchDtrpgCommand.py` |
| MCP modules | `mcp/rpg_geek.py`, `mcp/dtrpg.py` |
| MCP tools | `search_rpg_geek`, `lookup_rpg_geek_product`, `search_dtrpg` |

## New dependencies

- `httpx` (async, RPGGeek client) — not currently a dependency of this
  project.
- `requests` (sync, DTRPG client) — not currently a dependency of this
  project. Kept alongside `httpx` rather than normalizing both clients onto
  one HTTP library — the async/sync split between the two vendored clients
  is real (see "Commands" above), and forcing one client onto the other's
  library isn't worth the churn for two vendored files.

## Config / environment

Two new optional env vars, both read by their respective vendored client,
documented in `.env.example` and README's install section:

- `RPGGEEK_BEARER_TOKEN` — optional; `RpgGeekClient` logs a warning and
  proceeds unauthenticated if unset (RPGGeek's XML API works without auth
  for basic search/lookup, per upstream).
- `DTRPG_API_KEY` — required for `search_dtrpg` to function at all;
  `search_dtrpg` calls fail with a clear error if unset (server startup is
  unaffected, per the lazy-construction design above).

Also recommend installing the companion
[`openlibrary-mcp-server`](https://github.com/cyanheads/openlibrary-mcp-server)
alongside `rpg-librarian-mcp` (documented in README) — a separate MCP
server for Open Library book/author data, no API key required, useful for
the same product-identification workflow these tools serve.

## Open items / explicitly out of scope

- **Product-write tool** (`identify_product` or similar) — takes a
  `ProductLookupDetails` (or a caller-chosen `ProductCandidate` plus a
  follow-up lookup) and writes/updates `Product`, setting
  `identification_method` to `rpggeek_match`/`drivethru_match`. Not
  designed here (see brainstorm Q1) — deferred to its own spec once real
  usage patterns from these three read-only tools are observed.
- **`creators` → `Product.artists` reconciliation** — `Product` has no
  `authors`/`designers` field today; whether to add one, rename `artists`,
  or fold creators into `artists` is a decision for whatever spec adds the
  write-tool above.
- **No rate limiting added for DTRPG** — `RpgGeekClient` already
  rate-limits itself (1s sleep before each call, vendored as-is);
  `DriveThruRPGClient` does not, and none is added here — matches upstream
  behavior, revisit if DTRPG usage patterns show a need.
- **No on/off toggle inside the server** — clarified mid-brainstorm: "turn
  on/off" refers to enabling/disabling the single consolidated
  `rpg-librarian-mcp` server at the MCP-client/harness level (e.g. Claude
  Code), not a config flag inside this project. All tools register
  unconditionally, same as every existing tool.
