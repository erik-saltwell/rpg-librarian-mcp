# Brendan comparison refinement — 2026-10-10

A second metadata-only pass over the same completed remote inventory, refining the [baseline comparison](comparison.md). No RPG content was downloaded, remote data edited, catalog aliases added or production catalog records changed. The local catalog was opened read-only. These are comparison-specific associations and ownership assumptions, not confirmed product assignments or byte-identical remote matches.

## Results

| Classification | Files | PDFs |
|---|---:|---:|
| No local filename match — candidate | 12,241 | 8,942 |
| Likely owned — line, filename and size | 12,203 | 9,181 |
| Likely owned — renamed PDF evidence | 1,540 | 1,540 |
| Ambiguous filename/context | 199 | 107 |
| Likely owned — distinctive filename and size, unknown local line | 160 | 125 |
| Matching line/filename, different size | 20 | 18 |
| Likely owned — distinctive filename and size across line classifications | 4,943 | 4,402 |

Of 31,306 eligible files, **18,846 are likely owned**, **12,241 have no local filename/title match**, and **219 remain ambiguous**. This identifies **9,021 additional likely-owned files** compared with the baseline. It includes **1,540 renamed PDFs**. Remaining download candidates total **12,460 files / 131.18 GiB**, about **93.63 GiB less** than the baseline estimate. Candidate counts still include renamed or otherwise duplicate content the heuristics did not identify; they are not confirmed new products.

The PDF subset has 24,315 records: 15,248 likely owned, 8,942 missing-name candidates and 125 ambiguous. The unchanged exclusions are 1,886 files under underscore-prefixed folders and 169 organizing/control files. No source ancestor exclusions were loosened.

## Rules used in this pass

- Compare line names and existing aliases with punctuation/case normalization and equivalent numeric edition labels, preserving edition distinctions. Comparison associations cover 231 source lines through 264 relationships. Broader source-name associations require at least three distinct matching filenames with equal exact byte sizes. These associations help explain overlap; they are not persisted as library-wide aliases or used to change filing assignments.
- Accept a distinctive normalized filename plus equal exact byte size as likely owned even when the two catalogs classify it under different lines. This applies the user's acceptance of filename matching. Generic, very short or purely numeric names do not gain this filename-only shortcut. Record this weaker evidence separately from line-based matches. A shared source folder can contain products the user files under different lines; shared files are not evidence that those lines are interchangeable.
- For renamed PDFs, require mapped line context, equal exact byte size and an equivalent distinctive filename or catalog-product-title fingerprint. Split camel case, normalize punctuation and omit articles/conjunctions; remove a matching leading line name. Keep numbers/version/year words, with an optional local product-year suffix only when the catalog records that year. The source June catalog title is supplemental evidence when a current filename key exists in it. Require all local matching occurrences to share one known local SHA-256 identity; multiple/unknown identities remain ambiguous. No remote hashes or bytes were obtained, so this remains a metadata assumption.
- Keep size conflicts and unresolved matches as candidates, without creating review gates or automatically emailing thousands of comparison uncertainties.

## Renamed-copy examples

- Brendan: `7th Sea/Adventures & Scenarios/7th Sea 2e - Op'a on Board.pdf`; local: `games/7th Sea/7th Sea 2e - Op-a on Board.pdf`.
- Brendan: `7th Sea/Extras/7th Sea 2e - Explorer's Society - Conditions.pdf`; local: `games/7th Sea/7th Sea 2e - Explorer's Society - Conditions/7th Sea 2e - Explorer-s Society - Conditions.pdf`.
- Brendan: `13th Age/Adventures & Scenarios/Dungeons of Drakkenhall.pdf`; local: `games/13th Age/The Dungeons of Drakkenhall.pdf`.
- Brendan: `13th Age/Adventures & Scenarios/Make Your Own Luck.pdf`; local: `games/13th Age/Make Your Own Luck/13thAge-MakeYourOwnLuck.pdf`.
- Brendan: `13th Age/Adventures & Scenarios/The Elf Queen's Enchantment.pdf`; local: `games/13th Age/The Elf Queen-s Enchantment.pdf`.

## Evidence and limits

[Full refined CSV](/home/eriksalt/.local/state/rpg-librarian/brendan-preflight/refined-comparison.csv) records each current path, classification, baseline classification, reason, local IDs and example occurrences. [Comparison line associations](/home/eriksalt/.local/state/rpg-librarian/brendan-preflight/comparison-line-mappings.csv) records mapping basis and shared-filename evidence. Baseline CSVs remain available for comparison. Private helpers and evidence live under `~/.local/state/rpg-librarian/brendan-preflight/`; no credential values are included in these reports.

Count totals and PDF totals agree with the baseline inventory. A spread sample of 20 newly classified line matches, 20 filename/size matches and 20 renamed matches passed actual local size and whole-second mtime checks: 60 of 60. This is a sample, not a full local freshness audit or remote byte comparison. Missing-marked local rows are excluded; other rows are assumed present. Equal size and plausible names can still hide revised content, an accepted tradeoff for download efficiency.

The next implementation step is to carry these matching methods and provenance into the bounded importer, with candidate revalidation before transfer and exact duplicate detection after download. This comparison helper is a proof of behavior, not the production nightly runner. Complete incremental delta-cycle behavior, token refresh after expiry, run-scope enforcement, review/digest handling and scheduling still need implementation/integration verification.
