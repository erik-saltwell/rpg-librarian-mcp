---
name: "extract from brendan"
status: complete
---

# Extract from Brendan

Create a process that finds RPG content in Brendan's OneDrive that is missing from my library, copies it into my inbox, and processes it. Support a large one-time initial import followed by an ongoing job I can run nightly, with email notifications when items need my review.

## Context and requirements

- Brendan has his own system for ingesting and organizing RPG content, focused mainly on PDFs, and stores his content in OneDrive.
- His OneDrive is a personal account, and the folder is already shared with my Microsoft account.
- We share content with each other. He has almost all of my PDF content, but not my other product types.
- Find content he has that I do not already have, and move it through my inbox and processing workflow.
- Preserve his folder structure when copying new content into my inbox because he has already done substantial organizing.
- Ignore every underscore-prefixed folder and all descendants at any depth.
- Accommodate a very large initial import and subsequent nightly runs.
- Send me email when items require review.

## Documents

- [Accepted workshop decisions and open questions](idea.md)
- [Intent and approved quality rubric](intent.md)
- [Technical design](design.md)
- [Implementation plan](plan.md)
- [Implementation progress and manual handoff](progress.md)
- [Qualitative assessment](evaluations.md)
- [Integration preflight and remaining setup](preflight.md)
- [Baseline metadata comparison](comparison.md)
- [Refined metadata comparison](comparison-refinement.md)

## Completion and resume note

Manual importer implementation is complete and verified. It queues all eligible missing descendants of a selected top-level source folder and waits for that whole transfer group before scanning, pack discovery, enrichment, filing or placement. Read progress.md for actual architecture, verification and limitations, and the application README for manual commands. The user will run it repeatedly on real content before returning for nightly scheduling. No timer was installed or production RPG files imported during verification. Existing OneDrive/Gmail configuration remains usable; exact schedule hour/timezone and real-backlog rollout observations are future setup inputs.
