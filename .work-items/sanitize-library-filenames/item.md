---
name: "Sanitize library filenames"
status: complete
---

# Sanitize library filenames

Sanitize new library filenames and migrate existing production filenames while preserving extensions and keeping disk paths and catalog records aligned.

Allowed: Unicode letters and numbers, ordinary spaces, and `- _ . & $ # @ % ^ ( ) [ ]`. Replace other characters with dashes; normalize typographic dashes; remove trailing spaces/dots; handle Windows device names. Preserve compliant names. Resolve case-insensitive collisions with numbered suffixes before the extension, deterministically by file ID. Cleanup must be idempotent and previewable.

Implemented and applied to production: 2,666 filename renames with 3 collision suffixes. Repeated cleanup proposes no changes. See [progress](progress.md) for verification, limitations, backup, and journal.
