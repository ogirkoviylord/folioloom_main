# Production Scheduler Design

## Context

FolioLoom is moving from in-process Telegram translation toward durable paid
translation jobs. The current dev branch already has SQLite-backed persistent
jobs, persistent work units, local object storage, stored work-unit execution,
parallel local execution helpers, cancellation, resume primitives, run logs, and
TXT/DOCX/EPUB persistent planning.

The missing piece is a real scheduler. The scheduler must not be a temporary
queue wrapper that will later be replaced. It must define the production state
machine now, so local development, PostgreSQL migration, workers, payment
events, cancellation, resume, and history all converge on one contract.

## Decision

Use a PostgreSQL-first scheduler. PostgreSQL is the source of truth for job
state, work-unit state, leases, attempts, retries, cancellation, resume,
assembly, and worker heartbeats.

Workers claim due work transactionally with `SELECT ... FOR UPDATE SKIP LOCKED`.
Redis is not required for correctness in the first production design. A Redis,
LISTEN/NOTIFY, or outbox-driven notifier may be added later as a wake-up layer,
but it must only accelerate polling. If the notifier disappears, workers must be
able to recover by scanning PostgreSQL due rows.

This avoids split-brain queue state, keeps crash recovery boring, and matches
the requirement that all paid work can be rebuilt from persisted rows.

## Goals

- Never translate or charge a completed work unit twice.
- Continue from the last completed unit after bot restart, worker crash,
  machine restart, provider failure, or user cancellation.
- Keep job history and user-visible status rebuildable from persisted state.
- Make cancellation cooperative: no new units are claimed after cancellation,
  while in-flight provider requests finish or expire through leases.
- Make retries explicit, bounded, delayed, and auditable.
- Keep local dev storage compatible with the production state machine.
- Let provider/API-key limits, per-user limits, and global worker limits be
  enforced before work is claimed.

## Non-Goals

- Do not introduce Redis as a required queue in the first production slice.
- Do not implement payment provider integration inside the scheduler.
- Do not make the Telegram process a scheduler. Telegram remains an adapter.
- Do not replan documents automatically when adapter, prompt, protection, or
  policy versions are incompatible. Incompatible resume is explicit and visible.

## Architecture

The scheduler has four layers:

1. Domain state in PostgreSQL:
   `translation_jobs`, `translation_work_units`, `work_unit_attempts`,
   `worker_heartbeats`, and `scheduler_events`.
2. Scheduler repository:
   a narrow interface for creating jobs, claiming units, extending leases,
   completing units, failing attempts, cancelling, resuming, and listing history.
3. Worker orchestration:
   long-running workers that repeatedly claim due units, execute translation,
   persist results, and trigger assembly.
4. Optional notification:
   outbox, PostgreSQL `LISTEN/NOTIFY`, or Redis wake-up messages. Notifications
   are hints only; PostgreSQL due rows remain authoritative.

The existing `SQLiteTranslationJobStore` should evolve toward the repository
contract and remain a dev adapter. The production implementation should be a
PostgreSQL repository with the same orchestration API, not a separate behavior.

## Data Model

### `translation_jobs`

Core fields:

- `id`
- `order_id`
- `user_id`
- `source_file_id`
- `source_object_key`
- `file_name`
- `document_kind`
- `source_language`
- `target_language`
- `adapter_version`
- `prompt_version`
- `protection_version`
- `output_contract_version`
- `translation_policy_signature`
- `pricing_snapshot_id`
- `status`
- `priority`
- `available_at`
- `cancel_requested_at`
- `resume_blocked_reason`
- `partial_object_key`
- `final_object_key`
- `created_at`
- `updated_at`

Recommended statuses:

- `queued`
- `translating`
- `assembling`
- `partial`
- `ready`
- `cancel_requested`
- `cancelled`
- `interrupted`
- `failed`
- `expired`

`failed` is reserved for terminal non-resumable failure. Provider failure after
bounded retries should normally become `interrupted` when the work-unit plan can
still be reused.

### `translation_work_units`

Core fields:

- `id`
- `job_id`
- `sequence`
- `source_block_ids_json`
- `source_object_key`
- `source_text_hash`
- `prompt_tier`
- `source_language`
- `target_language`
- `status`
- `available_at`
- `lease_until`
- `worker_id`
- `claim_token`
- `attempt_count`
- `max_attempts`
- `last_error_code`
- `last_error_message`
- `translated_text`
- `translated_object_key`
- `prompt_tokens`
- `completion_tokens`
- `cache_hit_tokens`
- `cache_miss_tokens`
- `created_at`
- `updated_at`
- `started_at`
- `completed_at`

Recommended statuses:

- `pending`
- `translating`
- `translated`
- `failed_retryable`
- `failed_terminal`
- `cancelled`
- `skipped`
- `cached`

The current `failed` status should be split conceptually into retryable and
terminal failure before production. This prevents a worker from treating all
failures as the same kind of interruption.

### `work_unit_attempts`

Each provider attempt gets an immutable row:

- `id`
- `work_unit_id`
- `job_id`
- `attempt_number`
- `worker_id`
- `claim_token`
- `started_at`
- `finished_at`
- `status`
- `error_code`
- `error_message`
- `retry_after_seconds`
- `provider_request_id`
- `prompt_tokens`
- `completion_tokens`
- `cache_hit_tokens`
- `cache_miss_tokens`
- `source_text_hash`
- `output_text_hash`
- `validation_warnings_json`

This table is the audit trail for paid work and the place to debug bad provider
behavior without overloading the mutable work-unit row.

### `worker_heartbeats`

Fields:

- `worker_id`
- `worker_kind`
- `started_at`
- `last_seen_at`
- `active_job_id`
- `active_work_unit_id`
- `version`
- `hostname`
- `status`

Heartbeats are operational evidence, not lock ownership. Lock ownership remains
the work-unit lease and `claim_token`.

### `scheduler_events`

Append-only event stream for important transitions:

- `job_created`
- `work_unit_planned`
- `work_unit_claimed`
- `lease_extended`
- `work_unit_completed`
- `work_unit_retry_scheduled`
- `work_unit_failed_terminal`
- `job_cancel_requested`
- `job_cancelled`
- `job_resumed`
- `job_interrupted`
- `assembly_started`
- `partial_result_assembled`
- `final_result_assembled`
- `job_ready`

This can later drive notifications, admin views, and metrics.

## Claim Algorithm

Workers claim work inside one transaction.

Eligibility:

- job status is `queued` or `translating`;
- job has no `cancel_requested_at`;
- work-unit status is `pending` or `failed_retryable`;
- work-unit `available_at <= now()`;
- work-unit has no live lease;
- user, job, provider key, and global concurrency limits allow another claim;
- source file has not expired or been deleted.

The claim query should use `FOR UPDATE SKIP LOCKED` so many workers can compete
without blocking one another. The selected unit is updated to `translating` with
`worker_id`, `claim_token`, `lease_until`, incremented `attempt_count`, and
`started_at` if this is the first attempt.

Every completion, failure, or lease extension must include the same
`claim_token`. If the token does not match, the worker result is stale and must
be ignored or recorded as a stale completion attempt.

## Leases

Leases protect against dead workers and late provider responses.

- Default lease should be longer than the expected provider timeout plus retry
  delay budget for one unit.
- Long units may extend the lease through `extend_lease(claim_token)`.
- A scheduler maintenance loop requeues expired `translating` units by moving
  them to `failed_retryable` or `pending`, depending on retry policy.
- A late worker may not complete a unit after another worker has reclaimed it,
  because the `claim_token` no longer matches.

This is the critical mechanism that prevents duplicate completion after crashes.

## Retry And Backoff

Retry policy is per work unit and persisted.

Retryable examples:

- provider timeout;
- retryable HTTP status;
- temporary network failure;
- malformed provider output that can be repaired by retrying or splitting;
- lease expiration.

Terminal examples:

- source object missing;
- unsupported adapter version;
- corrupted original file;
- output mapping cannot be reconstructed safely;
- max retry attempts exhausted for a non-repairable unit.

When a retryable attempt fails:

1. insert a `work_unit_attempts` row;
2. set work unit to `failed_retryable`;
3. set `available_at = now() + backoff`;
4. clear `worker_id`, `claim_token`, and `lease_until`;
5. keep the job `translating` if other work can proceed, otherwise let the
   worker loop continue claiming when the retry is due.

After max attempts, mark the unit `failed_terminal` and the job `interrupted`
when resume/manual retry is still possible, or `failed` when the job cannot be
recovered.

## Cancellation

Cancellation is job-level and cooperative.

On user cancellation:

- set `translation_jobs.cancel_requested_at`;
- move job status to `cancel_requested`;
- prevent new claims;
- leave currently leased units alone until they complete or expire;
- after no live leased units remain, assemble partial output from completed
  units and mark the job `cancelled`;
- keep pending units resumable.

The scheduler should not try to abort an active LLM request. Provider calls may
be expensive and not always cancellable. The safety rule is that no new unit may
start after cancellation is requested.

## Resume

Resume should be explicit and guarded.

Before resume:

- source file object exists;
- adapter version is compatible;
- prompt version is compatible;
- protection/output contract versions are compatible;
- translation policy signature is unchanged;
- source text hashes match persisted work units;
- result assembly mapping is still usable.

If compatible:

- clear `cancel_requested_at`;
- clear `resume_blocked_reason`;
- set resumable pending/failed units to `pending`;
- set `available_at = now()`;
- set job status to `queued`;
- do not touch `translated`, `cached`, or safely `skipped` units.

If incompatible:

- keep the job blocked;
- set `resume_blocked_reason`;
- show a calm user-facing explanation;
- require replan, migration, or new order depending on the reason.

## Assembly

Assembly is a scheduled stage, not an incidental side effect of the final worker.

When all non-terminal units are finished or cancellation has settled:

- mark job `assembling`;
- assemble TXT/DOCX/EPUB from persisted completed units and original source;
- attach `partial_object_key` or `final_object_key`;
- mark job `partial`, `cancelled`, `ready`, or `interrupted`.

Rules:

- TXT partial output preserves layout through the last completed translated
  segment and omits the unprocessed tail.
- DOCX partial output replaces translated blocks and leaves untranslated blocks
  in the original language.
- EPUB partial output follows spine reading order and leaves the rest untouched.
- A malformed unit that cannot be mapped should become skipped/failed according
  to the adapter policy, not destroy the whole paid job.

Separating assembly gives users accurate states such as "translated but
assembling" and makes crash recovery simpler.

## Fairness And Limits

Claiming must enforce limits before work starts.

Initial limits:

- max active units per job;
- max active jobs per user;
- max active units per user;
- global max active units;
- provider/API-key max active requests;
- maximum queued bytes per user;
- maximum retry budget per job.

Fairness should prefer:

1. older paid jobs;
2. jobs with fewer active units;
3. users with fewer active jobs;
4. priority boosts only when explicitly set by admin or product policy.

The first implementation can keep fairness simple with ordered due rows, but the
schema should include `priority` and active-count checks now.

## Worker Runtime

A worker loop should:

1. heartbeat;
2. repair expired leases due for cleanup;
3. claim one or more due units;
4. execute translation;
5. complete, retry, or terminally fail the unit with the claim token;
6. trigger or claim assembly work when needed;
7. sleep with jitter when no work is due.

Workers should be horizontally scalable. Running two workers must be safe. A
worker crash must leave at most a leased unit that becomes reclaimable after
lease expiry.

## Observability

The scheduler should emit structured events for every state transition. Run logs
should keep fragment diagnostics, while scheduler events keep durable state
changes. These are related but not identical.

Minimum metrics:

- queued jobs;
- due work units;
- leased work units;
- expired leases;
- retry count by reason;
- interrupted jobs;
- cancellation latency;
- assembly failures;
- provider token totals;
- active workers and last heartbeat.

## Migration From Current Dev Code

Current code should not be discarded. It becomes the local adapter and test bed.

Recommended path:

1. Define scheduler repository dataclasses and methods around the production
   contract.
2. Adapt `SQLiteTranslationJobStore` to the new method names and fields where
   practical.
3. Update `worker.py` helpers to use claim tokens, explicit lease handling, and
   retry outcomes.
4. Move Telegram confirmation away from direct `until_idle` execution and toward
   creating jobs plus invoking the scheduler/worker path.
5. Add a PostgreSQL implementation after the interface and tests are stable.
6. Add optional notifier only after PostgreSQL polling works correctly.

The implementation should preserve the current persistent planner and assembler
work. The main change is where orchestration decisions live.

## Testing Strategy

Unit tests:

- ordered claim with `SKIP LOCKED` equivalent behavior;
- claim token required for completion;
- stale completion rejected;
- lease extension;
- expired lease recovery;
- retryable failure schedules delayed retry;
- max retries marks interruption;
- cancellation blocks new claims and preserves completed units;
- resume reuses completed units;
- incompatible resume is blocked;
- assembly is idempotent.

Integration tests:

- two workers cannot complete the same unit;
- worker crash leaves reclaimable work;
- cancellation during active work produces partial output;
- resume after restart continues from the next pending unit;
- DOCX/EPUB partial assembly keeps untranslated sections intact.

PostgreSQL tests should cover real transaction behavior. SQLite tests remain
useful for local state-machine coverage but must not be the only concurrency
evidence.

## Open Implementation Notes

- The exact lease duration should be configurable and initially conservative.
- The first production repository can use PostgreSQL polling every few seconds
  before any notifier is added.
- Provider/API-key pool state may remain in memory at first, but active request
  limits should also be reflected in persisted claim decisions before public
  traffic.
- Billing events should be idempotent and tied to completed work-unit attempts,
  but payment integration remains a separate design.
