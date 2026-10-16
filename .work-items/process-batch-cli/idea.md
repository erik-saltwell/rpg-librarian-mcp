# Process-batch CLI: accepted workshop idea

Provide a single RPG Librarian CLI invocation taking a catalog reference and an
input folder reference to run the existing batch-processing pipeline unattended.
Replace the final interactive review session with selective email notification and
a saved local run summary. Rerunning the same command is the normal recovery action
after interruption.

The owner approved this version at the close of the workshop. Detailed design,
planning, and implementation have not started.

## Processing sequence and scope

Follow the sequence in [scripts/process-batch.zsh](../../scripts/process-batch.zsh):

1. Quick duplicate cleanup, retaining the script's input-folder scope and its
   behavior of continuing with the normal scan if quick deduplication fails.
2. Scan the specified input folder.
3. Discover packs in that input folder.
4. Enrich the catalog.
5. Run the agent's `/process-batch` filing workflow.
6. Reorganize the catalog's files.
7. Record the run outcome and total review backlog, and apply the notification
   rules below instead of launching `/review-items` interactively.

The input folder restricts scanning and pack discovery; it does not newly restrict
enrichment, agent filing, or reorganization. Those retain the script's catalog-wide
scope. Quick duplicate cleanup remains scoped to the input folder as in the script.

## Review backlog

Include all four queues that the
[review-items skill](../../apps/rpg-librarian/src/rpg_librarian/resources/skills/review-items/SKILL.md)
would report:

- Open review flags.
- Files or packs blocked by reorganization.
- Unresolved pack discovery, including folders judged to be packs but left as loose
  files because of mixed decisions, invalid responses, or errors.
- Deferred organization-review recommendations.

Count outstanding review items across the entire catalog, regardless of the input
folder or whether this run created or changed them. The count represents the owner's
total review backlog, including unchanged unresolved items from earlier runs.

## Selective email and local summary

Send no email when either condition applies:

- There was nothing new to scan, regardless of the existing review backlog.
- Everything ran to completion and processed successfully with no review items.

For other cases, send an email containing the run outcome, completed or failed
stages, and the total catalog-wide review backlog. Thus a run with new scan work
and a nonempty backlog qualifies even when the backlog was unchanged; a failed run
with new scan work also qualifies even if the review backlog is empty.

Always save a concise local run summary containing the same outcome and backlog
information, whether or not email is sent. When email is skipped, record why. This
lets the owner distinguish a quiet run with nothing new from successful processing
with no outstanding reviews without reading detailed logs.

These rules replace the initial idea's simpler rule of emailing whenever the
backlog is nonempty. The added outcome information helps distinguish partial
processing from successful completion; selective delivery avoids unnecessary inbox
traffic. The local record preserves visibility for runs that do not generate email.

## Recovery through safe rerunning

Rerunning the same command after an interruption should preserve completed work,
recognize files and filing decisions already handled, and continue outstanding
work without manual cleanup. This makes the ordinary invocation useful for both
routine processing and recovery. A separate resume command or elaborate checkpoint
system was not agreed or required by this workshop.

Actual recovery reliability remains to be demonstrated. An in-process email step
alone cannot report a hard crash that prevents the command from sending mail; the
workshop did not select an external watchdog or a particular crash-recovery design.

## References and remaining design questions

- The production script is `~/data/rpg-librarian/process-batch.zsh`; at the time of
  discussion it matched the repository script linked above.
- [Brendan review notifications](../../apps/rpg-librarian/src/rpg_librarian/imports/notifications.py)
  provide existing SMTP delivery behavior to consult. Their suppression of already
  delivered unchanged reviews does not define this command's notification rules.
- CLI spelling, orchestration, stage-failure behavior beyond the quick-deduplication
  fallback, how completed work is recognized on retries, the precise meaning of
  new scan work for changed files and retries, and how overlapping review queues
  contribute to the total count remain detailed-design questions.
- The local summary's location, retention, and behavior during hard interruptions
  have not been specified.

See [intent.md](intent.md#quality-rubric) for the unchanged approved quality rubric
and [evaluations.md](evaluations.md) for the workshop's qualitative assessments.
