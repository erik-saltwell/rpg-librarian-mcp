# Nightly sync recovery and resilience

October 22 and 23 failed on HTTP 503 from redirected content transfers, which had
no retries. October 21 failed on Graph metadata HTTP 401 after about one hour;
expiry is likely but unproven. The client held one token for a two-hour budget.
All three failed during classification, with no new publication. Preserve existing
imports/brendan.sqlite3, content proofs, local hash cache, and verified download cache.

## Implementation

- [x] Add five bounded attempts for storage failures (429, transient 5xx, connection
  errors, interrupted/short streams), fresh download locations, safe partial restart,
  deadline-aware backoff, jitter, Retry-After seconds/date, and response cleanup.
- [x] Reuse an MSAL-backed credential provider, renew before expiry, refresh once
  after Graph 401, persist refreshed credentials privately, and retain token-string
  compatibility for older callers.
- [x] Write private JSONL request diagnostics beside each run summary. Include
  operation/item/phase, attempt, status, request IDs, timings, byte counts and retry
  decisions; never signed URLs, tokens, raw bodies or exception messages.
- [x] Record classification progress and unresolved items; continue after isolated
  exhausted transfers, stop after three consecutive exhausted files, and never
  admit incomplete classification.
- [x] Mark temporary service failures deferred for the next scheduled run;
  escalate the third consecutive service failure to a failed run and combined
  notification. Permanent failures retain immediate failure reporting. Success
  resets deferrals. Budget exhaustion is always quiet (October 25 follow-up below).
- [x] Verify controlled transport faults, credential renewal, classification safety,
  escalation, existing source lifecycle behavior, Ruff, types and diff checks.
- [x] Start the production service using the preserved state, inspect live diagnostics,
  and record its actual outcome or outstanding operational limitation.

Verification uses disposable behavior checks and existing checks; no repository unit
tests or test tooling will be created. The existing timer schedules the next attempt;
no new scheduler, retry loop, or automatic service restart is introduced.

## Verification and production recovery

Passed on October 23, 2026:

- `/tmp/check-sync-transport-resilience.py`: loopback HTTP transfer faults for
  429/500/502/503/504, interrupted streams, five-attempt exhaustion, permanent 404,
  fresh download URLs, bounded 401 credential refresh, Retry-After dates/seconds,
  deadline deferral, response/partial cleanup, no bearer token on storage requests,
  and no signed URL/body/credential material in diagnostics.
- `/tmp/check-sync-token-renewal.py`: cached-token reuse, renewal before expiry,
  forced renewal, and atomic persisted credentials with mode 0600.
- `/tmp/check-sync-request-records.py`: complete real provider/discovery/classification
  against loopback transport, recovered content 503, actual local ownership match,
  durable proof, private JSONL records, byte/progress metrics and redaction.
- `/tmp/check-sync-resilience-integration.py`: existing serial-source CLI/MCP/copy/SMTP
  behavior checks using controlled credentials, plus isolated exhausted-transfer
  continuation, zero publication with unresolved classification, third-run escalation,
  successful recovery and deferral-counter reset. All catalogs and email were local
  disposable fixtures. Existing integration hook/expectations were adapted only in
  `/tmp` for the new credential provider and transient/permanent outcome distinction.
- `/tmp/check-sync-breaker-budget.py`: stop after three consecutive exhausted files,
  no admission, and safe source-budget deferral.
- Ruff checks and formatting for all six changed Python files, full `ty check`, and
  `git diff --check` passed. No repository unit tests or tooling were added.

The production entry point resolves to this editable checkout. Started the existing
`rpg-librarian-sync.service` at 08:44:32 PDT on October 23. The CIFS preflight passed,
OneDrive discovery completed, and the new request log is mode 0600.

Live receipt:
`/home/eriksalt/data/rpg-librarian/logs/sync-sources/20261023T154433Z-771c0e22d9a3/summary.json`.
At the first recorded progress check: 31,314 observed, 4,200 examined, 4,075 owned,
125 pending so far, zero unresolved, zero new downloads and zero publications.
This confirms reuse of saved proofs; it is not a completed live sync. The pending
count already exceeds the automatic limit of 100, so a completed classification
will require manual import under the unchanged admission policy.

The service continues independently. Full live classification, live token renewal,
and recovery from a real remote outage remain operationally unverified. The next
existing nightly timer is October 24 at 03:00 PDT. No timer changes, commits, or
remote publication were performed.

## October 25 notification follow-up

The screenshot's October 23 03:46 email came from an HTTP 503 content failure
before the resilience changes. The recovery run and October 24 run then deferred
quietly on their budgets. October 25 incorrectly escalated ordinary budget
exhaustion to a failure email after three deferrals. Classification was progressing:
12,190, then 16,052, then 21,654 examined out of 31,314 observed; zero unresolved
items or publications in these receipts. This was not evidence of a stalled source.

- [x] Introduce `SourceBudgetExceeded`, a `TimeoutError` subtype, for explicit
  deadlines in OneDrive requests/backoff, discovery, classification, publication
  validation, and local ownership verification.
- [x] Always defer budget pauses without email/nonzero exit, and reset the service
  failure streak. Record `deferral_reason=source_budget_reached`. Preserve third-run
  escalation for actual temporary service failures and immediate permanent alerts.
- [x] Update the operator README and verify with a disposable catalog and mocked
  source/SMTP boundaries: five consecutive budget pauses send nothing; three HTTP
  503 failures escalate; a budget pause clears an existing failure streak; HTTP 403
  alerts immediately; success resets the counter. Actual OneDrive deadline and
  backoff methods emit the new exception. No real email was sent by verification.
- [x] Ruff lint/format, full `ty check`, and `git diff --check` pass.

The enabled timer's next trigger is October 26 at 03:00 PDT. Its launcher resolves
to this editable checkout, so the next run picks up the change. No production run
was started for this follow-up. Final live classification and admission/manual
notification remain pending; this broader recovery item remains implementing.

Quality evidence against the linked source-sync intent: appropriate owner
involvement improves by keeping routine deadline pauses quiet while retaining
persistent-service and permanent-error alerts. Safe continuity is supported by
unchanged durable journals and observed increasing live classification progress.
Correct recognition, overall nightly efficiency, and downstream workflow completion
were not re-assessed by this notification-only follow-up.
