# Asset pack support: evaluations

## 2026-10-02: implementation as built (uncommitted, branch `tooling-refactor`)

Evaluated against the approved [Quality rubric](intent.md#quality-rubric) (unchanged since
it was carried over from asset-pack-handling). The evidence is the checks recorded in
[plan.md](plan.md), run on the smoke fixtures and on copies of the live catalog. These are
qualitative judgments; the fixtures are small and partly fictional, so real-dump behavior is
judged from design plus fixture evidence.

**Pack integrity.** Good on the evidence available. On the fixtures, `find-packs` formed
exactly the five packs a person would name, kept Day/Night and Gridded/Gridless variants
and a deep `Harbor Maps`/`Harbor Tokens` layout inside one pack, split a category folder
into its two packs, and kept license and readme files with their packs. `reorganize`
moved each pack as one unit into its product folder with its structure kept. Scan keeps
members through content changes, adds new arrivals to the right pack, and never demotes a
member to a duplicate. Corrections hold: a pack emptied by hand is not re-formed by `find-packs`, and a one-member pack does not take new files (both fixed after review, `pack_dissolve_checks.py`). Weakness: boundaries on real, messy dumps depend on the model; that
is untested beyond the fixtures (the live catalog had nothing unfiled to judge).

**Evidence fidelity.** Good. Every formed pack stores the evidence summary and the model's
reason, and its folder search is kept as its Google evidence. Lossless formation held: the
half-filed folder was recorded `mixed` and left alone rather than overwritten, and
`create-pack`/`add-to-pack` report every decision a joining file gives up. Search hits are
passed to the model as corroboration only. One deliberate loss: a member PDF gives up its
own ISBN and catalog lookups.

**Usefulness with sparse evidence.** Strong. With `--no-search` the same five packs formed,
and the fictional packs (no DriveThruRPG or RPGGeek matches) were still filed and placed
from their folder names. Pooled readme and license text produced useful pack descriptions.

**Processing economy.** Good in the measured cases. Each fixture run asked the model 5 times
for 10 folders and searched 8 names (2 generic names skipped); reruns and a real run after a
dry run made no calls or searches. Enrichment made one lookup per pack per source and
skipped Google for packs `find-packs` had already searched. Filing a 25-file pack took one
`update_product` call. Unassessed at scale: the live catalog has no unfiled files, so the
real call and search load was not measured; it depends on how pack-migration adopts filed
products.
