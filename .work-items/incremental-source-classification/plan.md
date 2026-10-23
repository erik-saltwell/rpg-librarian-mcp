# Incremental source ownership classification

OneDrive observation already uses durable delta cursors. Classification still
rebuilds a catalog/inbox filesystem inventory and searches ownership candidates for
every eligible remote item. Saved content proofs and local hash signatures prevent
most byte rereads but not the repeated broad metadata work.

- [x] Persist exact remote ID/version/hash links to local root, catalog file ID when
  available, path, and verified filesystem signature. Existing journals migrate
  additively; no heuristic matches become proofs.
- [x] Validate linked copies directly; follow catalog file IDs through reorganizations.
  Changed signatures require exact rehashing. Missing/changed/unsafe paths fall back
  to broader matching; pending and unresolved items are never negatively cached.
- [x] Build candidate inventories lazily, only for sizes needing broad matching.
  Completely linked unchanged runs must not walk the inbox or inventory catalog
  files, download remote content or reread local bytes.
- [x] Perform weekly full ownership reconciliation, with `--full-reconcile` to force
  it. Complete partial weekly work across interruptions, then advance the timestamp
  only after classification completes. Expose reuse, indexing and hashing metrics.
- [x] Verify with disposable catalogs and direct behavior checks: cold/warm runs,
  mutations with restored mtime, moved/missing files, new local copies, remote
  content changes and deletions, unsafe paths, deadline/interruption recovery,
  scheduled/forced reconciliation, and existing source lifecycle checks.
- [x] Update operator documentation, run Ruff/type/diff checks, and record outcome.

No repository unit tests or test tooling will be added. An unchanged run still
checks each linked local file's current metadata so a local deletion is noticed
without waiting for a remote change. Weekly reconciliation is an ownership search;
it retains the existing precise-signature hash cache, rather than rehashing every
unchanged byte. No live service restart, new scheduler, or admission-limit change.

## Outcome and verification

Implemented in `sync/ownership.py`, `sync/ingestion.py`, `sync/runner.py` and the
CLI parser. Operator behavior is documented in the root and application READMEs.
New `sync_ownership` rows in each source journal contain exact remote ID/version/hash,
root ID, optional catalog file ID, local path, verified signature and reconciliation
time. Existing source journals gain the table additively on their next invocation.

Confirmed links are checked first. Unchanged links are not rewritten. Catalog
identity follows moved files; filesystem identity/size/nanosecond modification and
change times determine whether a byte hash can be reused. Directory ancestry and
final-file checks exclude symlinks and paths outside registered roots. Missing or
changed links fall back to a candidate inventory restricted to unmatched sizes.
Only exact matches are recorded. Completed links are checkpointed every 100 examined
files and during normal exception unwinding, retaining the existing durable source
proof/download behavior. A hard kill may redo the last uncommitted group of links.

Weekly/forced matching retains a durable starting timestamp. Links matched during
that cycle can be reused after interruption; older links undergo broad matching.
The completed-full-reconciliation timestamp advances only on complete classification.
All admission, source-failure continuation and notification policies remain intact.

Passed October 23, 2026:

- `/tmp/check-incremental-source-classification.py` used actual disposable SQLite
  catalogs, source journals and filesystem copies. It verified 1,000 cold matches,
  an unchanged warm run with inventory preparation, directory walking and byte
  hashing explicitly forbidden, catalog-tracked moves, restored-mtime same-size
  edits, newly added manual copies, removed local copies, file and parent symlinks,
  changed remote versions, preserved local bytes after remote removal, scheduled
  weekly/forced reconciliation and recovery of an interrupted reconciliation epoch.
- Local 1,000-file fixture: first classification 9.881 seconds; unchanged
  classification 0.062 seconds, 1,000 reused links, zero candidate inventories,
  zero local hashed bytes and zero downloads. These are fixture results, not a
  promise about SMB/production runtime.
- `/tmp/check-sync-request-records.py` passed complete provider/discovery/ownership
  recovery from a controlled 503 using loopback HTTP, private request logs and
  redaction. Its disposable inbox was registered to match the real CLI precondition.
- `/tmp/check-sync-resilience-integration.py` passed the existing serial-source,
  admission thresholds, update preservation, pipeline/MCP/copy/SMTP, failure
  continuation, recovery, isolated-transfer deferral and repeated-deferral checks.
- Ruff lint/format, full `ty check`, CLI help and `git diff --check` passed.

The production recovery service already running was not restarted or interrupted;
it uses the code loaded before these changes. Subsequent invocations use the new
classifier automatically through the editable checkout. The first such invocation
must establish local ownership links; existing verified content proofs are retained.
Production-scale performance and weekly operation over real SMB remain unverified.

## Quality observations

Against the existing source-sync quality context: exact recognition and safe
continuity are supported by the mutation, symlink and interrupted-reconciliation
checks. Proportionate effort is supported by the unchanged 1,000-file fixture,
with real-share performance still unassessed. Appropriate owner involvement and
workflow consistency retain the same admission/notification/shared-pipeline behavior,
verified by the existing lifecycle checks. No additional rubric was introduced.
