# Issue #283 Retry And Requeue Controls Design

Issue: #283
Status: architecture spike; not implementation approval
Date: 2026-06-04

## Routing Receipt

- Classification: `spike / discovery` plus `risky task`.
- Risk level: high.
- Primary role / skill: Architect Agent, `architecture-review`.
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`,
  `docs/superpowers/specs/2026-06-04-active-translation-admin-controls-spike.md`.
- Approval status for this PR: not required for docs-only design.
- Approval status for implementation/runtime operations: missing; any writable
  retry/requeue implementation needs a separate owner-approved issue.
- Allowed action in this PR: architecture documentation only.
- Verification plan for this PR: docs gate review and `git diff --check`.

## Source Evidence

Confirmed from current repository evidence:

- Work units have `attempt_count`, `max_attempts`, `retry_count`,
  `available_at`, `worker_id`, `claim_token`, `lease_until`, safe last-error
  metadata and persisted attempt rows.
- The scheduler can claim `pending`, `failed` and `failed_retryable` units only
  when the unit is available and has no active lease or an expired lease.
- `fail_claimed_work_unit` preserves attempt history, records an attempt row,
  records a scheduler event and sets retryable failures to
  `failed_retryable` with a bounded retry delay.
- Terminal work-unit failure can mark the job `interrupted`.
- `recover_expired_leases` turns expired `translating` leases into normal
  retry/terminal failure decisions instead of directly requeueing active work.
- `resume_job` currently moves `translating`, `failed` and
  `failed_retryable` work units back to `pending` and sets the job to `queued`.
- Scheduler work is blocked by beta safety `can_start_new_work` when the kill
  switch or global caps are active.
- Admin traces already surface retry metadata such as attempts, retry counts,
  safe provider-failure category and retry-after seconds.

Assumptions:

- The owner wants a narrow operator recovery tool for closed-beta incidents,
  not a broad manual retry system.
- The safest first implementation should recover from interrupted or retryable
  failed work without clearing attempts, hiding failures or creating duplicate
  provider traffic.

## Architect Verdict

SAFE as docs-only design.

NEEDS HUMAN APPROVAL before any implementation that mutates jobs, work units,
leases, provider traffic, beta safety accounting, user-visible outcomes or
runtime data.

## Allowed Retry/Requeue Targets

### Job-Level Requeue

Allowed only when all of these are true:

- Job status is `interrupted` or `failed`.
- The job has no active leased `translating` work units.
- At least one unfinished work unit is eligible under the work-unit rules
  below.
- Source object metadata required for unfinished units still exists and passes
  the existing accepted-source/upload-safety gate.
- Beta safety `can_start_new_work` allows new provider work at execution time.
- Provider runtime capacity is available through the existing scheduler/provider
  capacity path.

Not allowed without a separate explicit owner decision:

- `queued`, `translating`, `assembling` or `cancel_requested` jobs with active
  work.
- `ready` jobs.
- `partial` jobs where the partial result is intended as a terminal user result
  rather than an interrupted recoverable state.
- `cancelled` jobs unless the owner explicitly approves admin retry after
  cancellation.
- `paused` jobs; pause recovery should use the existing resume semantics, not
  retry/requeue.
- `deleted` or missing jobs.
- Bulk job requeue.

### Work-Unit Requeue

Allowed:

- `failed_retryable` units whose `attempt_count` is less than `max_attempts`,
  after their existing `available_at` delay or with a documented manual
  operator override in a separate implementation issue.
- `failed` units only when repository evidence shows they are legacy retryable
  rows and `attempt_count` is less than `max_attempts`.
- `pending` units do not need requeue; they are already claimable when the job
  is eligible.

Not allowed without a separate explicit owner decision:

- `translating` units with a live lease. Let normal lease expiry or cooperative
  worker completion resolve them.
- `translated`, `cached`, `skipped` units.
- `failed_terminal` units.
- Any failed unit at or above `max_attempts`.
- Units whose source object is missing or no longer accepted.
- Units that would require clearing attempts, deleting history, changing source
  text, changing prompts or creating a duplicate unit.

## State Transitions

Approved design target for a later implementation:

| Current state | Control | New state | Notes |
| --- | --- | --- | --- |
| job `interrupted` with eligible unfinished units | requeue job | `queued` | Do not reset attempts; only eligible units become claimable. |
| job `failed` with eligible unfinished units | requeue job | `queued` | Requires safe failure reason and no active leases. |
| unit `failed_retryable` below `max_attempts` | requeue unit | `pending` or keep `failed_retryable` until `available_at` | Preserve attempts and retry metadata. |
| unit legacy `failed` below `max_attempts` | requeue unit | `pending` or `failed_retryable` | Only if implementation proves legacy retryable semantics. |
| unit `translating` with expired lease | recover lease | existing retry decision | Use `recover_expired_leases`, not direct admin requeue. |

Rejected transitions:

- `failed_terminal` to `pending`.
- any terminal/translated unit to `pending`.
- clearing `attempt_count`, `max_attempts`, `work_unit_attempts` or
  `scheduler_events`.
- clearing a live `claim_token` or `lease_until` for active provider work.
- creating duplicate work units for the same source block.

## Attempt History And Retry Policy

Implementation must:

- preserve `work_unit_attempts`;
- preserve `scheduler_events`;
- preserve `attempt_count`, `max_attempts`, `retry_count` and
  `retry_after_seconds`;
- add a metadata-only admin event such as `translation.admin_requeued`;
- include actor id, role, job id, work-unit ids, previous states, new states and
  safe reason category;
- avoid raw document text, translated text, prompts, provider payloads, stack
  traces, object-storage keys, API keys or secret/provider internals.

Implementation must not:

- reset attempts to make work look new;
- hide terminal failures;
- retry above `max_attempts`;
- override provider adaptive throttling;
- bypass existing scheduler claim ordering, leases or capacity checks.

## Scheduler Leases And Provider Capacity

Retry/requeue controls must use the scheduler as the only path to new provider
traffic.

Required behavior:

- A live `translating` lease is authoritative.
- Admin requeue must not clear a live `worker_id`, `claim_token` or
  `lease_until`.
- Expired leases should be recovered through existing lease-expiry logic.
- The scheduler must check beta safety `can_start_new_work` before claiming new
  provider work.
- Provider runtime/adaptive capacity stays in the existing worker/provider
  path; admin requeue should not directly call a provider.
- Issue #30 guardrails remain: admin provider diagnostics must not compete with
  active provider work.

## Cost, Cap And Kill-Switch Behavior

Retried provider work is new provider work for operational safety purposes.

Required behavior:

- If the kill switch is active, requeued units may stay queued/retryable but the
  scheduler must not start provider calls.
- If global daily/monthly caps are reached, requeued units may stay
  queued/retryable but provider calls are blocked.
- Completed usage must remain idempotent per work unit; retrying must not double
  count a prior completed unit.
- Reservation/consumption behavior must stay beta-safety accounting, not a paid
  billing ledger.
- If a future implementation needs a new reservation or cap check for manual
  requeue, that must be spelled out in the implementation issue before coding.

## User-Visible Outcomes

My Books/history:

- Requeued jobs should remain visible as the same book/job, not a duplicate
  history item.
- Status can return from `interrupted` or `failed` to `queued` or
  `translating` once scheduler work resumes.
- Completed and cached units remain completed.
- Existing final or partial downloads remain available unless a separate
  owner-approved data/retention decision changes that behavior.

Partial result:

- Existing partial result should remain downloadable while requeue is pending,
  unless the later implementation proves a safer replacement rule.
- A later final result may supersede the partial result only through existing
  final-assembly behavior.

Status messages:

- User copy should be neutral: recovery is in progress, queued or failed.
- Do not expose admin actor names, provider internals, raw errors, stack traces,
  prompts, raw document text or translated excerpts.

## Implementation Split

If accepted, create a separate owner-approved implementation issue with:

- exact allowed job statuses and work-unit statuses;
- exact admin UI affordance and confirmation text;
- exact state-transition helper to implement;
- beta-safety reservation/cap behavior;
- lease handling and provider-capacity behavior;
- redaction fields for admin activity, audit, run logs and archive exports;
- rollback/disable plan for the control;
- focused verification commands.

Do not combine this with issue #282 pause/cancel/delete narrowing, issue #284
destructive delete, issue #285 redaction regression planning or issue #81 Gate
B operational evidence unless the owner explicitly says to combine them.

## Required Future Tests

Later implementation must include:

- Persistent job/store tests for allowed and rejected requeue transitions.
- Postgres scheduler tests for claim-token safety, active lease rejection,
  expired lease recovery and no duplicate provider work.
- Bot/service tests for My Books/history, partial download and status outcomes.
- Provider capacity/cost-safety tests proving kill switch and caps block
  retried provider work.
- Redaction tests for admin activity, audit, run logs, translation traces,
  summaries and archive exports.
- `PYTHONPATH=src python3 -m compileall src`.
- Full `PYTHONPATH=src python3 -m unittest discover -s tests` for shared
  admin/bot/scheduler changes.

