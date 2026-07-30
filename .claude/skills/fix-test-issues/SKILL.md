---
name: fix-test-issues
description: Work through the bug report from an rpg-librarian-mcp end-to-end test session (~/data/rpgtest/.errors.md), filing expected-behavior findings as test-skill notes and turning real bugs into failing tests plus a diagnosis for approval. Use when the user asks to process/fix/triage test issues, work through .errors.md, or act on results from the rpg-librarian-mcp-test skill.
---

# Fix Test Issues

## Goal

Turn a completed end-to-end test report into either (a) a documented,
non-reportable "known operating expectation," or (b) a failing regression
test plus a diagnosed, approved fix — never straight into an unreviewed
code change.

## Inputs

The report lives at `~/data/rpgtest/.errors.md`. Read the whole file before
acting on any single issue — the user may have already annotated entries
with `> **Update from user**: ...` notes marking them as expected behavior,
retracted, or otherwise out of scope. Those annotations are authoritative;
trust them over your own re-diagnosis of the same issue.

## Workflow

Process every numbered issue in the report, one at a time:

1. **Classify the issue.**
   - Marked expected behavior (explicit "EXPECTED BEHAVIOR — not a bug" /
     "not a bug" / "no action needed" framing, with or without a user
     annotation) → go to step 2, then stop for this issue. Do not write a
     test or propose a fix.
   - Anything else (a real defect, even a minor/polish one) → go to step 3.

2. **Document the expectation, take no other action.**
   - Edit `src/rpg_librarian_mcp/resources/skills/rpg-librarian-mcp-test/SKILL.md`
     (the packaged copy — this is what `--migrate` redeploys into a
     library's `.claude/skills/`, not any already-deployed copy under a
     library root).
   - Add one bullet to its `## Known operating expectations` section (create
     the section, right before `## Reporting bugs`, if it doesn't exist yet)
     stating the behavior plainly enough that a future test run recognizes
     it and doesn't re-report it: what input triggers it, what the correct
     observable outcome is (exact error text where the report gives one),
     and which tool(s) it applies to.
   - Do not touch application code or tests for this issue. Move to the next
     issue.

3. **Reproduce, diagnose, propose — don't fix yet.**
   - Read the relevant source under `src/rpg_librarian_mcp/` to understand
     the actual code path the report's repro steps exercise.
   - Write a failing unit test first, in the existing test file that already
     covers that tool/command (e.g. `tests/test_move.py`,
     `tests/test_update_catalog_command.py`, `tests/test_directory_status.py`,
     `tests/test_read_pdfs_command.py`) — match that file's existing
     conventions for fixtures/helpers rather than inventing new ones. Name
     the test after the observable bug, and give it a one-line docstring
     citing what broke and why (see existing "Bug: ..." docstrings in those
     files for the expected style).
   - Run just that test and confirm it fails, capturing the failure mode you
     expected from the report (a raised exception, a wrong return value,
     etc.) — not an unrelated error from a broken fixture.
   - Diagnose the root cause by reading code, not by guessing from the
     symptom alone.
   - Present the diagnosis and a concrete proposed fix to the user and wait
     for approval before editing any non-test source file. If several
     issues in the report are being processed in one pass, batch the
     diagnoses so the user can approve/reject each independently rather than
     stopping after every single one.
   - Only after approval: apply the fix, re-run the new test (and the full
     suite) to confirm it now passes, and check whether the fix also
     resolves — or should be paired with a note for — any other issue in the
     report that shares the same root cause.

## Constraints

- Never mark something as an expected-behavior note based on your own
  judgment alone if the report doesn't already say so — ask the user first.
  The report is expected to carry the user's own classification; don't
  second-guess it, but don't invent one for an issue that's ambiguous either.
- Keep each `Known operating expectations` bullet self-contained: a future
  reader of the test skill won't have this conversation's context, so name
  the tool(s), the triggering input, and the exact expected outcome.
- Run `uv run pytest -q` for the whole suite before declaring any fix done,
  not just the new test.
