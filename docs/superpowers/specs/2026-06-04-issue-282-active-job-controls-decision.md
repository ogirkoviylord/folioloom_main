# Issue #282 Active Job Controls Decision Record

Issue: #282
Status: owner decision recorded for pause/cancel narrowing; destructive delete
requires separate owner-approved implementation scope
Date: 2026-06-04

## Routing Receipt

- Classification: `spike / discovery` plus `risky task`.
- Risk level: high; destructive delete is critical if expanded or operated on
  runtime data.
- Primary role / skill: Architect Agent, `architecture-review`.
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`,
  `docs/superpowers/specs/2026-06-04-active-translation-admin-controls-spike.md`.
- Approval status for this PR: approved with owner evidence in the current
- Approval status for implementation/runtime operations: missing for any new,
  expanded, destructive, deployment, schema/state, auth/security, privacy,
  payment or runtime-data operation.
- Allowed action in this PR: architecture documentation only.
- Verification plan for this PR: docs gate review and `git diff --check`.

## Source Evidence

Confirmed from current `main`:

- Admin route `POST /admin/operations/jobs/{job_id}/{action}` accepts
  `pause`, `cancel` and `delete` after admin session and CSRF checks.
- Operations summaries mark queued/running jobs as `pausable` and
  `cancellable`; queued/running/paused jobs are marked `deletable`.
- `pause_job` sets the job status to `paused`, resets in-flight
  `translating` work units to `pending`, and prevents new claims until
  `resume_job` returns the job to `queued`.
- `cancel_job` sets the job status to `cancelled`, resets in-flight
  `translating` work units to `pending`, and preserves completed work-unit
  translations.
- `delete_job` removes the persistent job, work units, work-unit attempts and
  scheduler events. The admin route also collects source, partial, final and
  work-unit source object keys and deletes those objects through local object
  storage.
- Admin actions record metadata-only user activity events and finish running
  translation logs with safe generic messages.
- Bot status copy already has admin paused and admin deleted messages.

Owner decision evidence:

  destructive active-job delete out of #282 and approved continuing with the
  separate-delete decision path.

Unknown / TBD:

- Runtime safety of destructive active-job delete across backups, restore,
  retention, object storage and user-visible history is not proven by this
  issue and remains separate implementation scope.

## Architect Verdict

SAFE for this PR as docs-only architecture decision.

NEEDS HUMAN APPROVAL for destructive delete semantics and any expanded writable
behavior beyond the decision recorded here.

## Owner Decision

Recorded decision:

1. Keep `pause` as an allowed single-job admin control for queued and
   translating/running jobs only.
2. Keep `cancel` as an allowed single-job admin control for queued and
   translating/running jobs only.
3. Do not approve destructive `delete` in #282. Treat active-job delete as a
   separate critical-risk implementation scope after the #284 architecture
   review.
4. Do not add bulk pause/cancel/delete controls in this issue.
5. Do not add retry, requeue or mark-failed controls in this issue; those are
   owned by issue #283.

This recommendation does not approve runtime operations, schema/state changes,
storage deletion, deployment, public admin exposure, payment behavior or release
readiness.

## Allowed Control Semantics

### Pause

Allowed affected states:

- `queued`
- `translating`
- normalized admin `running` states that map to active scheduler work

Not allowed without a separate issue:

- terminal states: `ready`, `partial`, `cancelled`, `failed`, `expired`
- destructive states or storage/object deletion
- bulk jobs

Required confirmation:

- Admin CSRF/session confirmation remains required.
- Future UI should add a clear single-job confirmation before changing
  scheduler state.

Required behavior:

- Preserve completed work units and attempt history.
- Stop new claims while paused.
- Do not clear safe audit/activity history.
- Do not bypass beta allowlist, cost caps, kill switch, provider capacity or
  issue #30 provider-request guard.
- User-visible status may say the translation was paused by an admin, without
  raw document text, translated text, prompts, provider payloads, stack traces
  or secret/provider internals.

### Cancel

Allowed affected states:

- `queued`
- `translating`
- normalized admin `running` states that map to active scheduler work

Not allowed without a separate issue:

- `ready`, except as a future explicit archive/delete policy
- destructive storage deletion
- paid/refund behavior
- bulk jobs

Required confirmation:

- Admin CSRF/session confirmation remains required.
- Future UI should add a clear single-job confirmation explaining that
  cancellation may leave a partial result if completed work exists.

Required behavior:

- Preserve completed work-unit translations and safe partial-result behavior
  where available.
- Preserve attempt history, scheduler events and metadata-only run logs.
- Cooperate with in-flight provider work; do not create split-brain claims or
  duplicate provider traffic.
- Release or preserve beta-safety reservation only through already approved
  tested cancellation paths.
- User-visible status may say cancelled and show partial availability, without
  raw document text, translated text, prompts, provider payloads, stack traces
  or secret/provider internals.

### Delete

Decision status:

- Destructive active-job deletion is not approved in #282.
- Issue #284 owns the destructive-delete architecture review.
- Any future delete implementation or UI expansion requires a separate
  owner-approved implementation issue.

Current-main affected data classes from repository evidence:

- persistent job row;
- work units;
- work-unit attempts;
- scheduler events;
- source object key;
- partial result object key;
- final result object key;
- work-unit source object keys;
- running translation log status, through a safe finish helper;
- metadata-only user activity event.

Data classes that remain relevant to separate delete implementation scope:

- backup/restore artifacts;
- retention/TTL expectations;
- audit/activity retention requirements;
- user-visible My Books/history recovery expectations;
- object-storage edge cases and missing-object handling;
- run-log archives and summaries after delete.

Required confirmation if delete is separately approved later:

- Explicit destructive warning.
- Single-job scope only.
- Exact data classes listed before execution.
- No live runtime deletion outside an owner-approved exact-run environment.

## Required Future Tests

Later implementation or narrowing must include:

- Admin route/rendering tests for visible controls and confirmation UX.
- Persistent job/store tests for allowed state transitions.
- Postgres scheduler tests for lease and claim-token behavior.
- Bot/service tests for paused, cancelled, partial and deleted user-visible
  status.
- Translation run-log tests for safe action events.
- Redaction tests proving normal admin/log/archive/API surfaces stay
  metadata-only.
- `PYTHONPATH=src python3 -m compileall src`.
- Full `PYTHONPATH=src python3 -m unittest discover -s tests` for shared
  admin/bot/scheduler changes.

## Required Approval Gates

Owner approval is still required before:

- expanding or changing pause/cancel semantics;
- adding or expanding destructive delete behavior;
- touching database/schema/state contracts;
- touching runtime `var/`, object storage or live server data;
- changing backup/restore, retention or TTL behavior;
- changing auth/RBAC/admin exposure;
- changing payment/pricing/billing;
- making release, beta-ready or production-ready claims.

