# Issue #284 Destructive Active-Job Delete Review

Issue: #284
Status: architecture spike; not destructive-operation approval
Date: 2026-06-04

## Routing Receipt

- Classification: `spike / discovery` plus `risky task`.
- Risk level: critical for destructive delete implementation or runtime
  operation.
- Primary role / skill: Architect Agent, `architecture-review`.
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`,
  `docs/deployment/restore-runbook.md`, and
  `docs/superpowers/specs/2026-06-04-active-translation-admin-controls-spike.md`.
- Approval status for this PR: not required for docs-only review.
- Approval status for destructive implementation/runtime operation: missing;
  exact owner approval is required before any delete expansion, live runtime
  deletion, runtime `var/` access, storage mutation or backup/restore operation.
- Allowed action in this PR: architecture documentation only.
- Verification plan for this PR: docs gate review and `git diff --check`.

## Source Evidence

Confirmed from current repository evidence:

- Admin active-job delete calls `store.delete_job(job_id)` and then deletes
  collected object-storage keys through `LocalObjectStorage.delete`.
- User My Books delete uses the same persistent job deletion pattern and object
  key deletion path for the user's own job.
- SQLite and Postgres persistent stores delete the persistent job row, work
  units, work-unit attempts and scheduler events.
- Admin delete records metadata-only user activity and admin audit events.
- Running translation logs are finished with a safe generic cancelled/deleted
  message; run-log directories and archive files are not deleted by the
  current admin delete path.
- `LocalObjectStorage.delete` removes both the object file and its metadata
  sidecar.
- Current docs mark TTL/delete verification and backup/restore rehearsal as
  incomplete Gate B areas.
- Owner-approved retention/delete verification may use synthetic data by
  default and owner-approved disposable runtime copies for a second pass; live
  beta/server cleanup checks are forbidden without exact owner approval.

Unknown:

- Whether current-main active-job delete should remain visible for active jobs.
- Whether current backup exports should preserve enough deleted-job evidence
  for recovery/audit expectations.
- Whether current run-log archives after delete are sufficient for support and
  incident review.

## Architect Verdict

NEEDS HUMAN APPROVAL.

Recommendation: do not expand active-job delete. Prefer safer cancel/archive
semantics for active jobs until the owner explicitly approves destructive
delete scope, confirmation UX, audit retention and backup/restore impact.

This PR does not approve destructive operations, code changes, schema/state
migrations, runtime-data access, deployment, payment behavior or release
readiness.

## Data Classes Affected By Delete

### Persistent Job

Current effect:

- The persistent job row is deleted.
- Job status and metadata are no longer available through normal persistent job
  lookup.

Impact:

- My Books/history loses the normal job source of truth.
- Resume/retry/requeue cannot operate on the deleted job.
- Recovery depends on backups, run logs and activity/audit metadata rather than
  live job state.

### Work Units

Current effect:

- Work-unit rows are deleted.
- Unit statuses, translated-text fields, source block ids, source object keys,
  token usage and lease fields are removed.

Impact:

- Partial/final assembly cannot be reconstructed from live scheduler state.
- Effective translation export cannot overlay current work-unit progress after
  deletion.

### Attempts

Current effect:

- Work-unit attempt rows are deleted.

Impact:

- Attempt count history, safe failure categories and retry-after evidence are
  no longer available from persistent state.
- Incident review depends on scheduler events, run logs or audit snapshots if
  they were preserved elsewhere.

### Scheduler Events

Current effect:

- Scheduler event rows are deleted.

Impact:

- Lease, retry, claim and terminal-failure timeline evidence is lost from live
  scheduler state.
- This weakens post-incident analysis unless activity/audit/run-log evidence is
  intentionally retained.

### Run Logs

Current effect:

- Running translation logs are finished with a safe generic status/message.
- Run-log directories, `run.json`, `events.jsonl`, summaries and downloadable
  archives are not deleted by the current admin delete path.

Impact:

- Normal logs may still show metadata for a deleted job.
- If future delete removes logs too, it becomes a stronger destructive action
  and needs separate explicit approval plus redaction/backup tests.

### Object Storage

Current effect:

- The admin delete path collects and deletes:
  - source object key;
  - partial result object key;
  - final result object key;
  - work-unit source object keys.
- `LocalObjectStorage.delete` removes the object file and metadata sidecar.

Impact:

- User-visible source/result downloads are no longer available.
- Restore becomes backup-dependent.
- Missing-object behavior must be idempotent and safe.

### Activity And Audit Records

Current effect:

- Admin delete records a metadata-only `translation.admin_deleted` activity
  event and an admin audit event.
- The metadata includes safe job identifiers and document metadata such as file
  name, document kind, language direction, notification message and status.

Impact:

- Activity/audit records are the main remaining live evidence after persistent
  state is deleted.
- They must stay redacted and must not include raw document text, translated
  text, prompts, provider payloads, object keys, stack traces, API keys or
  secret/provider internals.

### User-Visible History

Current effect:

- My Books/history can no longer load the deleted persistent job through normal
  job lookup.
- Bot status copy can display deleted status only when deletion evidence is
  available through activity-derived fallback paths.

Impact:

- Users may lose access to partial/final downloads.
- Recovery messaging must be explicit and neutral.
- Cancel/archive may be safer than destructive delete for active jobs because
  it preserves history and partial-result expectations.

## Retention And TTL Impact

Confirmed policy:

- Source default: 7 days after final/cancel/delete, or immediate on explicit
  delete where safe.
- Final default: 30 days or until delete.
- Partial default: 14 days.
- Quarantine default: 7 days.
- Logs: metadata only.
- Audit/security: longer retention, redacted.

Issue #284 conclusion:

- Immediate active-job delete is stronger than TTL cleanup and can remove
  recoverable data before Gate B TTL/delete verification is complete.
- Delete must be idempotent for missing DB rows and missing storage objects.
- Delete must not erase the only metadata needed to prove what happened.
- Until TTL/delete verification is complete, active-job destructive delete
  should be treated as critical and should be narrowed or replaced with
  cancel/archive by default.

## Backup, Restore And Recovery Impact

Current recovery concern:

- Backup/restore evidence expects restored jobs/work units, user-visible
  history, files and admin/beta settings to be usable enough for beta recovery.
- Deleting live persistent state and object storage before backup can make the
  deleted job unrecoverable except from older backups.
- Deleting run logs or audit/activity records would further reduce incident and
  support evidence.

Required before any release-related use:

- Metadata-only backup/restore impact note.
- Synthetic fixture proving delete outcome is reflected consistently in backup
  exports and restore rehearsal.
- Explicit owner decision on whether restore should recover deleted jobs,
  preserve tombstones only, or intentionally omit deleted files.
- No raw document text, prompts, translations, API keys, secrets, backup
  archives or restored files in PRs/issues/docs.

## Confirmation UX If Delete Remains Allowed

Required confirmation:

- Single-job scope; no bulk delete.
- Visible destructive warning.
- Show safe metadata only: job id, order id, sanitized file name, document kind,
  language direction, status, unit counts and available result types.
- Explicitly list affected data classes before execution.
- Require a second deliberate confirmation control, not a one-click table
  button.
- Show whether the action will delete source, partial, final and work-unit
  source objects.
- State that restore may depend on backup availability and owner-approved
  restore process.

Forbidden confirmation content:

- Raw document text.
- Translated text.
- Prompt bodies.
- Provider payloads or provider responses.
- Object-storage keys.
- Runtime file paths.
- Stack traces.
- API keys, secret ids or provider account internals.

## Audit Requirements If Delete Remains Allowed

Required metadata:

- actor id and role;
- timestamp;
- target job id and order id;
- channel and safe user reference;
- sanitized file name;
- document kind;
- source and target language;
- previous job status;
- previous unit counts by status;
- object classes affected, not raw object keys;
- result availability before delete;
- confirmation version;
- outcome and safe reason.

Retention:

- Audit/activity tombstone metadata should remain after deletion.
- Deleting audit/activity evidence requires separate owner approval and a
  retention/legal/privacy review.

## Recommended Decision

Recommended owner decision for issue #284:

1. Do not expand destructive active-job delete for now.
2. Replace future active-job destructive delete work with safer cancel/archive
   semantics unless the owner approves exact destructive scope.
3. Keep any existing current-main delete behavior under critical-risk watch
   until a separate implementation issue narrows the UI or adds explicit
   confirmation/audit safeguards.
4. Use synthetic fixtures only for tests unless the owner approves an exact
   disposable environment or runtime copy.
5. Do not perform live runtime deletion, backup mutation, restore rehearsal or
   `var/` access in this issue.

## Required Future Tests

Later implementation or narrowing must include:

- Persistent job/store tests for deleted row and tombstone/audit expectations.
- Postgres scheduler tests for work units, attempts and scheduler events.
- Object-storage deletion tests using synthetic fixtures only.
- Admin route/rendering tests for confirmation UX and rejected bulk delete.
- Bot/service tests for user-visible deleted/cancelled/history behavior.
- Translation run-log and redaction tests.
- Backup/restore impact note before release-related use.
- `PYTHONPATH=src python3 -m compileall src`.
- Full `PYTHONPATH=src python3 -m unittest discover -s tests` for shared
  admin/bot/scheduler/storage changes.

