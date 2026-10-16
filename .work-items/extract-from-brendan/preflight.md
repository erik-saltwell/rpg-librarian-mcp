# Extract from Brendan — integration preflight

Checked on 2026-10-10 before importer implementation. This records actual prerequisite evidence and the remaining live checks; it does not establish end-to-end importer readiness. Status remains planning.

## Latest Graph proof — 2026-10-10

This section supersedes the earlier pending Microsoft registration/authorization checks below. The user registered RPG Librarian Brendan Import for personal Microsoft accounts, enabled public-client flows and added delegated Files.Read.All. Device authorization succeeded; cached silent token acquisition subsequently succeeded. At the user’s request, client configuration and source IDs now live in the ignored repository-root `.env`. The token cache remains in `~/.local/state/rpg-librarian/brendan-preflight/msal-cache.json`, referenced by `.env`. Both the `.env` and cache have mode 0600. Private preflight helpers explicitly load that `.env`, respecting existing environment variables. Silent acquisition and direct shared-folder metadata access were rechecked successfully after migration. The obsolete private config.json and source.json were removed. `.env.example` documents the six `RPG_LIBRARIAN_ONEDRIVE_*` keys without actual values. The scheduled runner must explicitly load the chosen `.env`; current app commands do not yet implement the importer.

The deprecated sharedWithMe bootstrap did not locate the archive. A remote-item reference in the user's own drive resolved Brendan's actual drive/root identity instead. Direct target metadata and a paginated children request succeeded: the archive has 400 immediate children; two underscore-prefixed folders appeared in the sampled page and were excluded from the reported eligible sample. A first delta page succeeded with a continuation link. Full baseline traversal, a terminal delta checkpoint and a later incremental cycle remain unverified.

A bounded content request downloaded only `catalog.json`, 1,435,090 bytes, through a separate request that did not forward Graph authorization headers to the download redirect. Size and JSON parsing passed. A private local copy is available beside the setup helpers. Graph reports modified time 2026-06-21T00:30:20Z; the catalog's generated/enriched date is 2026-06-20. It contains 7,476 records across 130 product lines, each with `file`, `system`, `title`, `group`, `type`, `size_mb`. There are no hashes, full relative paths or per-file modification dates. Browser inspection found 76 repeated case-insensitive product-line/filename combinations, so those keys are not unique identifiers.

The user accepts filename-based skipping, preferably within matching product lines, to avoid downloading likely-owned content. Product-line folders provide matching and filing context. Use the catalog as a metadata seed; its age and incomplete paths require current Graph metadata for additions, exclusions, path resolution and ambiguous records. Download selected candidates in bounded resumable batches, never the entire share as a prerequisite. No PDFs were downloaded, production catalog rows changed, email sent or timer installed.

Next: reconcile the catalog with local filename/product-line evidence, complete current remote metadata discovery and measure candidate counts. Gmail private configuration and authentication are now verified. Remaining setup includes exact nightly time and actual scheduler/filing execution; the user-requested email test was subsequently received. Silent acquisition proves cache reuse, not refresh after token expiry.

## Gmail setup verified — 2026-10-10

Gmail SMTP host/port/implicit-TLS settings are now configured in the ignored repo-root `.env`. Sender, app password and review recipient fields were added empty, preserving existing settings. `.env.example` documents `RPG_LIBRARIAN_SMTP_HOST`, `RPG_LIBRARIAN_SMTP_PORT`, `RPG_LIBRARIAN_SMTP_TLS`, `RPG_LIBRARIAN_SMTP_USERNAME`, `RPG_LIBRARIAN_SMTP_PASSWORD` and `RPG_LIBRARIAN_REVIEW_EMAIL_TO` with placeholders only.

The user completed Google setup and populated sender, app password and recipient directly in the ignored `.env`. The file remains mode 0600. Credentials and account addresses are omitted from this record.

A private `mail_probe.py` helper is ready beside the OneDrive setup helpers. It explicitly loads repo `.env`, uses certificate-verified SMTP SSL, authenticates and disconnects without sending email or logging credentials. Its first run correctly reported three missing settings: sender, app password and recipient. After the user supplied the settings, the probe passed certificate-verified TLS and Gmail SMTP authentication (235). Recipient configuration passed the probe’s format check; deliverability has not been tested. No email was sent. The future importer/digest adapter has not been implemented.

Dotenv discovery was subsequently checked in normal standalone processes from both the checkout and an unrelated folder containing its own `.env`: app load_env found the repo-root `.env` in both cases and ignored the unrelated file. CLI and MCP startup share that loader. Explicit loading in private setup scripts is appropriate; the earlier blanket requirement for scheduled source-checkout app commands was too broad. Installed copies, interactive/debugger execution and catalog-path selection have separate behavior.

## Current metadata comparison completed — 2026-10-10

The full paginated Graph baseline completed in 37 pages/about 93 seconds and retained a terminal delta checkpoint privately. It observed 36,194 current files/folders. After reconstructing all ancestry, 31,306 files were eligible across 386 folders with eligible content; 1,886 files under underscore-prefixed folders and 169 root/per-line organizing control files were separated. No file had unresolved ancestry. These counts supersede the partial-page observations above.

Comparison streamed 383,347 present-marked local catalog rows and retained only 22,226 relevant filename candidate occurrences. Results: 9,825 likely-owned files, 13,772 missing-filename candidates, 7,709 ambiguous matches. Thirty sampled likely-owned local occurrences matched actual size/whole-second mtime. This does not establish byte equality or a full freshness audit. Candidate volume before mapping refinements/exact duplicate checks is about 224.81 GiB. See [comparison.md](comparison.md) for criteria, examples, PDF counts and private CSV links. Naming differences mean candidate counts are not confirmed new content. No RPG files were downloaded and the production catalog was read-only. A subsequent incremental delta cycle remains unverified.

The user-requested Gmail test email was accepted by SMTP, and the user confirmed receipt. Transport and delivery are now verified; the importer digest adapter remains unimplemented.

## Matching refinement completed — 2026-10-10

A second pass over the same inventory used comparison-specific product-line associations, distinctive filename/exact-size evidence across differing classifications, and renamed-PDF title/filename evidence with equal sizes and one local hash identity. This identified 9,021 additional likely-owned files, including 1,540 renamed PDFs. The refined totals are 18,846 likely owned, 12,241 missing-name candidates and 219 ambiguous, with about 131.18 GiB in remaining candidates. These are metadata assumptions, not confirmed remote equality. Sixty spread samples of newly classified local matches passed actual size/mtime checks. Production catalog and remote source remained unchanged; no RPG content was downloaded. See [comparison-refinement.md](comparison-refinement.md) for criteria, limits and private CSV evidence. These estimates supersede the baseline candidate counts above.

## Confirmed decisions

- Brendan uses personal OneDrive; the RPG Archive folder is already shared with the user's Microsoft account. The user supplied its browser locator and completed browser sign-in.
- Exclude every folder beginning with `_` and its complete subtree, at any depth. Apply this to discovery and transfer eligibility, including parent moves/renames.
- Gmail SMTP will send actionable review digests, using this machine's systemd user timer for nightly execution. The user approved both. Exact nightly hour/timezone remain unconfirmed; 02:00 America/Los_Angeles was proposed.
- Preserve source hierarchy and provenance, allow uncertain imports without review gates, and send only nonempty digests of newly actionable reviews. Earlier accepted workshop decisions remain applicable.

## Verified local prerequisites

| Check | Actual evidence | Practical limit |
|---|---|---|
| Live catalog | `/home/eriksalt/data/rpg-librarian/catalog.db`, schema `0006`, about 953 MiB; 383,348 file rows, all with SHA-256; one marked missing | Hash presence alone does not prove every file remains present/current |
| Registered roots | Library `/phinneas/rpg/library` (root 1); staging `/phinneas/rpg/inbox` (root 2) | Nested roots are rejected by `commands/add_source.py`; reuse root 2 with `brendan/` prefix |
| Existing workload | 8,436 unfiled staging files; 266,106 unfiled library files; no open review flags at inspection | Importer must scope work by provenance/file IDs and avoid whole-catalog processing |
| Small freshness sample | Latest eight file rows from each root matched on-disk size and whole-second mtime | Sixteen sampled files, not a complete freshness/hash audit |
| Destination | SMB/CIFS mount reachable; about 2.6 TiB free; local disk about 933 GiB free | Source volume remains unknown; recheck mounts/free space each run |
| Publication semantics | Temporary hidden inbox probe passed exclusive creation, write/flush/fsync, readback and same-filesystem non-replacing rename; overwrite refused | Probe files removed; crash recovery and large transfers still need implementation verification |
| Scheduler | User systemd running, timers target active, user lingering enabled | No importer timer installed; unattended mount/credential execution not yet checked |
| Agent | Claude CLI 2.1.296 installed and logged in; live library has MCP configuration and processing/review skills | Actual filing and mutation-scope enforcement remain unverified |
| Headless MCP | `claude -p` called `mcp__rpg_probe__list_product_types` on a temporary catalog; returned the seeded marker, no permission denials; server wide event recorded successful `list_product_types` | Read-only call, not a filing batch. Temporary catalog removed. CLI safe mode disabled MCP in the first attempt; explicit strict MCP configuration without safe mode succeeded |
| Email network | Certificate-verified TLS connection and successful SMTP EHLO to `smtp.gmail.com:465` | No authentication or message sent |
| Existing credentials | No Microsoft client ID/token cache or mail credentials found in checked local configuration; rclone's configured remote is Google Drive | No reusable OneDrive connection was established; secret values were not printed |

The successful agent probe used `--tools ''`, `--permission-mode dontAsk`, an exact MCP tool allowlist, `--strict-mcp-config`, `--setting-sources ''`, JSON output and no session persistence. Schedule with explicit executable/catalog/project/configuration paths. Do not infer success from subprocess exit zero: confirm catalog outcomes and server events.

## Verified browser access

After user sign-in, the shared OneDrive page displayed RPG Archive and game-organized folders such as 13th Age, 2300 AD and 7th Sea. It also displayed `_delete_by_brendan` and `_superseded`, which the exclusion rule must skip. The list inspected was a partial rendered view, not a complete inventory or size estimate.

A nested-folder navigation was initiated, but further inspection and the Entra registration page could not be completed because browser automation became unavailable. Reported errors included `Preview automation snapshot timed out after 15000ms` and `No preview automation host is available for snapshot`. No application registration or remote content modification was performed.

Browser sign-in proves UI access only. The supplied URL is a OneDrive navigation URL with path parameters; do not assume it is directly resolvable by Graph's shares API or manufacture Graph IDs from its account identifier. Keep the locator in private host configuration rather than checked-in documents.

## Remaining account setup and proof

1. Establish an application client ID for delegated public-client authentication supporting personal Microsoft accounts. The proposed application name is RPG Librarian Brendan Import. Enable public-client flows; use MSAL device authorization and the personal-account authority. A public client needs no client secret. Registration requires access to a suitable Entra directory; whether the user has that access is not yet known. Microsoft describes [app registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) and [public-client configuration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration).
2. Authorize once and privately persist the MSAL cache. Resolve the actual remote drive and root item IDs, verify ancestry and list a nested folder. Test shared-folder delta; use the documented recursive-inventory fallback if unavailable. Stream a small sample to temporary storage and prove silent token acquisition under the intended scheduler environment. Shared-link resolution may require broader delegated consent; see the design's permission discussion before selecting that path.
3. Configure Gmail sender, recipient and app password privately. [Google app passwords](https://support.google.com/accounts/answer/185833) require 2-Step Verification and are unavailable for some account configurations. If unavailable, use Gmail OAuth rather than the account's ordinary password. Per the user’s preference, store sender, recipient and app password in the existing ignored repo-root `.env` with mode 0600, using the keys above. Do not send a production test email without explicit instruction.
4. Confirm exact nightly hour/timezone, then prove the completed runner under systemd with explicit paths, credentials and mount checks. Installation follows a bounded end-to-end run, not this preflight alone.

## Design and plan corrections

The earlier proposal to register `inbox/brendan` as its own root conflicts with the existing catalog and overlapping-root prohibition. The revised design reuses root 2 plus an inbox-relative prefix. Preserve original source-relative ancestors explicitly for enrichment so `brendan/` does not become an organizing clue.

At the actual catalog scale, matching and work selection need indexed, paginated SQL and measured memory use. Existing global enrichment/reorganization and all-unfiled worklists cannot be the nightly runner. New underscore exclusions must handle delta-only observations, incomplete ancestry and renamed/moved parents, as well as recursive pruning. These corrections are incorporated into [design.md](design.md) and [plan.md](plan.md).

## Manual implementation verification — 2026-10-10

The app importer is implemented; see [progress.md](progress.md) for its architecture,
complete-folder barrier and verification evidence. Full and incremental live Graph
discovery and the production streaming adapter passed against scratch catalogs.
Real headless filing and a three-image pack passed using generated scratch files.
No Brendan RPG files were copied into the production inbox and no new production
email or timer was activated. The user will now run the importer manually before
returning for nightly setup; the exact hour/timezone remains deferred.
