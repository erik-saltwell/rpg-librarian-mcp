# Extract from Brendan — workshop decisions

## Intended outcome

Find RPG content in Brendan's OneDrive that my library lacks, copy it into my inbox, and process it. Brendan's collection is primarily PDFs and substantially overlaps mine. Preserve the value of his existing organization while supporting a very large initial import and an ongoing nightly job with minimal intervention.

Workshop concluded with the following accepted direction. These are design decisions, not verified implementation behavior. The approved [quality rubric](intent.md#quality-rubric) applies, including the added unattended-operation dimension.

## Accepted direction

### One continuing process

Use the same process for the initial import and ongoing nightly runs. Maintain a durable record of each discovered item's progress, distinguishing content already owned, copied, processed, and requiring review, as well as unfinished work. Later runs discover additions and continue or retry unfinished work instead of starting over. Review tracking does not make review a prerequisite for copying.

This provides continuity after interruptions and reduces repeated downloads, processing, and review requests. Storage and precise lifecycle details remain undecided.

### Paced catch-up with priority for new content

Drain the initial backlog gradually across nightly runs, prioritizing newly discovered content over older backlog items. The initial import need not finish in one enormous run.

This spreads resource use and downstream processing over time while keeping fresh additions flowing. The tradeoff is a longer catch-up period; sustained large arrivals could delay older items. Pacing limits and the treatment of that possibility remain unresolved.

### Progress without review gates

Allow uncertain matches to proceed into the inbox rather than holding them for review before copying. The user explicitly prefers frequent unattended progress and accepts that uncertainty can admit duplicates. Discovery accuracy still matters, but uncertain matching alone should not block copying.

The proposal to hold uncertain matches before copying was rejected and should not be reintroduced as an assumed requirement.

### Preserve organization and provenance

Copy content into the inbox with Brendan's folder structure intact. His organization should remain useful context during identification and processing; this is part of preserving his organizing work, rather than a separate feature.

Remember provenance, including source identity independently of the current folder path, so moves or renames can be recognized without importing the same file again merely because its location changed. A source identity does not by itself establish that file contents are unchanged; handling modified files remains to be designed.

The user expects the existing inbox processing to benefit naturally from the preserved hierarchy. Whether it currently uses parent folders has not been verified.

### Actionable review digests

Send at most one review digest per run, and only when it contains at least one item needing review. Include newly actionable items, explain what needs attention, and provide access to a persistent review list.

Previously reported, unresolved items remain in that list without being emailed every night. Report them again only when something material changes. A run with no newly actionable review items sends no digest. The tradeoff is less prompting about older unresolved reviews.

### Independent item failures

Let a failed download, unreadable PDF, or other individual item failure leave other work free to continue. Preserve progress and retry temporary failures on later runs. Persistent problems needing a user decision enter the review list; temporary failures do not automatically generate review email.

A shared failure, such as losing OneDrive access, can still affect an entire run. A run may finish with incomplete items, which must remain visible in its record. Retry policy and reporting for shared failures remain undecided.

## Resume and unresolved questions

Workshop is finished for now. The next useful activity is investigating existing behavior and defining the design; it has not started as part of this save.

- How to access and discover content in Brendan's OneDrive, including durable source identity and changed files.
- How to recognize content already in my library despite naming and organization differences.
- How existing inbox processing uses parent-folder context and handles preserved source paths.
- How to persist item progress, pace imports, and handle retries.
- Which conditions need a user decision, what makes an existing review materially changed, and how the review list is accessed.
- How to schedule nightly execution and deliver review email.

No implementation, integration inspection, or performance verification has been performed. These unknowns require investigation rather than additional conceptual features.

## Accepted setup refinements — 2026-10-10

Ignore every folder beginning with `_`, including all descendants at any depth. The user provided the shared personal-OneDrive folder locator and completed browser sign-in. Gmail SMTP and this machine with a systemd user timer are approved; the nightly hour/timezone remain unconfirmed. Keep the source locator and credentials in private host configuration. See [preflight.md](preflight.md) for evidence and remaining checks.

## Implementation scope update — 2026-10-10

The user authorized implementation for manual runs, with nightly scheduling deferred until after repeated manual use. Top-level source folders are durable transfer groups: once selected, queue every eligible missing descendant, finish that group over as many bounded runs as necessary, and only then scan/find packs/enrich/file/place it. Do not feed a partial transfer group into pack discovery. Already-owned files need not be copied. Underscore-folder and organizing-file exclusions remain applicable. A later discovery of additions reopens the folder transfer barrier.
