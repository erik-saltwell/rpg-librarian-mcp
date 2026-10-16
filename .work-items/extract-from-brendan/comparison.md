# Brendan metadata comparison — 2026-10-10

Baseline result; the later [refinement](comparison-refinement.md) supersedes these candidate estimates.

Current Graph inventory compared with the local catalog, without downloading RPG content. The existing private June catalog supplies supplemental context; current paths and sizes come from Graph.

| Classification | Files |
|---|---:|
| No local filename match — candidate | 13,772 |
| Likely owned — product line, filename and size | 9,629 |
| Ambiguous filename or product-line context | 7,683 |
| Likely owned — distinctive filename and size | 196 |
| Matching line/filename, different size | 26 |

Eligible inventory: 31,306 files across 386 product-line folders, 300.66 GiB. 1,886 files excluded through underscore-prefixed ancestors; 169 organizing control files separated (root catalog/reports and per-line _index.md); 0 files have unresolved ancestry.

Download candidates (missing filename or ambiguous): 224.81 GiB before exact duplicate checks. 25,176 current eligible files have no matching June catalog product-line/filename key.

## Interpretation and limits

Likely-owned is a metadata assumption, not verified byte equality. Comparison preserves edition/version words, case-folds Unicode and normalizes spaces, underscores and hyphens. Exact current byte size strengthens matches. Local product-line assignment/aliases take precedence over folder-derived context. Distinctive filename-only matches can count as likely-owned when local line context is unknown and that filename occurs in one remote line. Conflicting lines, generic filenames and size differences remain candidates. Local missing-marked rows are excluded; other catalog rows are assumed present without a full filesystem audit. Renamed local files can inflate missing-filename candidates. Current folder names that do not map through exact local line names/aliases remain unresolved context, not automatic new product assignments.

A complete paginated baseline reached a terminal Graph delta link, saved privately for a subsequent incremental check. This is not evidence that concurrent changes were absent or that a later incremental cycle has been verified. No remote writes, production catalog mutations, PDFs, enrichment calls or emails were performed.

Full per-file evidence is in [comparison.csv](/home/eriksalt/.local/state/rpg-librarian/brendan-preflight/comparison.csv); per-line counts are in [comparison-product-lines.csv](/home/eriksalt/.local/state/rpg-librarian/brendan-preflight/comparison-product-lines.csv).

## Examples

### No local filename match — candidate

- 7th Sea/Adventures & Scenarios/_Map_6-13-2016 — No matching normalized filename in present catalog rows; renamed copies may exist
- 7th Sea/Adventures & Scenarios/2nd Edition V2.pdf — No matching normalized filename in present catalog rows; renamed copies may exist
- 7th Sea/Adventures & Scenarios/7th Sea 2e - Op'a on Board.pdf — No matching normalized filename in present catalog rows; renamed copies may exist
- 7th Sea/Adventures & Scenarios/7th Sea The Blue Books - Waves of Blood.pdf — No matching normalized filename in present catalog rows; renamed copies may exist
- 7th Sea/Adventures & Scenarios/A Murder of Supplication An Epic Ussuran Adventure.pdf — No matching normalized filename in present catalog rows; renamed copies may exist

### Likely owned — product line, filename and size

- 7th Sea/Adventures & Scenarios/7th Sea 2e - Attack on Eisen.pdf — Matching product-line context, normalized filename and exact size
- 7th Sea/Adventures & Scenarios/7th Sea 2e - Quickstart.pdf — Matching product-line context, normalized filename and exact size
- 7th Sea/Adventures & Scenarios/7th Sea 2e - Release the Kraken.pdf — Matching product-line context, normalized filename and exact size
- 7th Sea/Adventures & Scenarios/7th Sea 2e - Who Killed Lord Wojcik (2018).pdf — Matching product-line context, normalized filename and exact size
- 7th Sea/Adventures & Scenarios/7th Sea 2e [JWPA015] 7th Sea Adventures - Natural Law.pdf — Matching product-line context, normalized filename and exact size

### Ambiguous filename or product-line context

- 13th Age/Settings & Sourcebooks/Charsheet.pdf — Filename found locally, but product-line context is conflicting/unknown, name is generic, or size differs
- Achtung Cthulhu/Adventures & Scenarios/Kontamination - Printer Friendly V1.pdf — Filename found locally, but product-line context is conflicting/unknown, name is generic, or size differs
- Achtung Cthulhu/Adventures & Scenarios/Shadows of Atlantis.pdf — Filename found locally, but product-line context is conflicting/unknown, name is generic, or size differs
- Achtung Cthulhu/Extras/Achtung_Cthulhu_Dossier_-_Tales_from_the_Crucible.pdf — Filename found locally, but product-line context is conflicting/unknown, name is generic, or size differs
- Achtung Cthulhu/Player & GM Aids/Elder Godlike - Maps.pdf — Filename found locally, but product-line context is conflicting/unknown, name is generic, or size differs

### Likely owned — distinctive filename and size

- ACKS/Adventures & Scenarios/Autarch - Domains at War Campaigns.pdf — Distinctive filename and exact size; local product-line context unknown
- ACKS/Settings & Sourcebooks/Autarch - Domains at War Battles.pdf — Distinctive filename and exact size; local product-line context unknown
- Apothecaria/Player & GM Aids/Deck of Time.pdf — Distinctive filename and exact size; local product-line context unknown
- Blades in the Dark/Settings & Sourcebooks/Glow in the Dark Playbooks V8.pdf — Distinctive filename and exact size; local product-line context unknown
- Delta Green/Player & GM Aids/Delta_Green_Digital_Assets_International_Pack_1_-_Europe_colour.pdf — Distinctive filename and exact size; local product-line context unknown

### Matching line/filename, different size

- ACKS/Core Rules/AUT1004_PDF_Domains_at_War_Free_Starter.pdf — Product-line and filename match, but size differs
- Call of Cthulhu/7th Edition/Rules/Nameless_Horrors.pdf — Product-line and filename match, but size differs
- Delta Green/Adventures & Scenarios/DG Gods Light 1.pdf — Product-line and filename match, but size differs
- Delta Green/Adventures & Scenarios/Scenarios/Delta_Green_Observer_Effect.pdf — Product-line and filename match, but size differs
- Delta Green/Adventures & Scenarios/Scenarios/Music From a Darkened Room 3.pdf — Product-line and filename match, but size differs

## PDF subset

| Classification | PDFs |
|---|---:|
| No local filename match — candidate | 10,473 |
| Likely owned — product line, filename and size | 7,019 |
| Ambiguous filename or product-line context | 6,643 |
| Likely owned — distinctive filename and size | 156 |
| Matching line/filename, different size | 24 |

## Verification and next refinement

The baseline completed 37 metadata pages in about 93 seconds, with 36,194 current file/folder observations and zero unresolved file ancestry. Thirty selected likely-owned occurrences were checked on the local filesystem: all thirty matched catalog size and whole-second mtime. This small sample does not establish freshness of every local match and no bytes were compared.

The comparison is deliberately preliminary. Product-line naming differences and local filename changes can inflate candidates. For example, a Brendan filename in Achtung Cthulhu matches a local file under the more specific catalog line Achtung! Cthulhu (Classic- Call of Cthulhu, Savage Worlds and Fate), but lacks an established line mapping and therefore remains ambiguous. Map equivalent line names and examine renamed-PDF patterns before estimating how much is truly new. Do not treat any of the candidate counts as verified new products or create thousands of review emails from comparison ambiguity. The accepted unattended policy still permits uncertain imports.

This is a setup comparison, not an implemented nightly runner. Inventory and comparison helpers, private metadata SQLite database, terminal delta link and CSVs remain under ~/.local/state/rpg-librarian/brendan-preflight/. Normalized-name indexes were built only for relevant remote names while streaming local rows; the production catalog was opened read-only. The June catalog is not authoritative for current discovery: 25,176 current eligible records have no matching June product-line/filename key, which can reflect later content or renamed/reorganized content. No RPG content was downloaded during this comparison.
