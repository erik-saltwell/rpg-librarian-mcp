# Sync registered download sources

Discover new and updated content from registered sources, exclude verified local
hash matches, independently admit manageable batches and process sources serially
through the shared batch pipeline. OneDrive is implemented first; the provider
interface supports adding other providers later.

## Approved multi-source behavior

- Register named sources separately from provider/account configuration. Initially
  support multiple OneDrive folders; Google Drive and Dropbox are future adapters.
- `sync-sources` selects all enabled sources by default, with explicit selection.
- Apply the default 100-file automatic admission threshold separately per source,
  after excluding verified local hash matches. Include new and updated content.
- Finish one source's discovery, classification, publication and shared processing
  before starting the next. Existing process-batch scopes and inbox bleed are fine.
- Zero pending files exit quietly, except explicitly admitted unfinished work is
  resumed. An oversized source is manual-only; other sources can proceed.
- Continue after source failures, return nonzero, and send one combined failure
  email after all sources have been attempted, even if no new files were discovered.
- Retain shared successful-run review reporting. Avoid separate per-source failure
  messages duplicating the combined failure notification.
- Preserve older local versions. Never propagate remote deletes or upload changes.
- Update production launchers safely; do not install a nightly scheduler.

## Quality rubric

Approved qualitative dimensions for judging the Brendan import refactor and its
intended effect: dependable nightly discovery and import with proportionate effort,
appropriate owner involvement, and consistent downstream processing.

- **Correct content recognition** — Values distinguishing genuinely new or updated
  content from files already owned, using trustworthy hash evidence.
- **Proportionate nightly effort** — Values network, disk, and processing costs that
  reflect actual changes, especially on nights when nothing needs importing.
- **Safe continuity** — Values preserving existing files and completed work across
  partial transfers, interruptions, and repeated runs.
- **Appropriate owner involvement** — Values leaving manageable batches unattended,
  respecting the boundary for manual handling, and drawing attention only when
  useful.
- **Workflow consistency** — Values Brendan imports following the same processing
  and reporting behavior as the shared process-batch workflow, without developing
  conflicting behavior.

Correct recognition and efficiency are independently assessable: ownership checks
can be accurate but expensive. Workflow consistency is distinct from reliability:
a separate import pipeline could work reliably while gradually behaving differently.
These dimensions support qualitative assessment in ordinary language, without
scores, rating scales, anchors, weights, or pass/fail thresholds.
