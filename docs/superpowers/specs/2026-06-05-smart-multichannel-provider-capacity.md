# Smart Multichannel Scheduling And Provider Capacity

Status: Recommended architecture note for the approved multichannel direction.
Date: 2026-06-05.
Related issues:
[#80](https://github.com/ogirkoviylord/folioloom_main/issues/80) discovery,
[#297](https://github.com/ogirkoviylord/folioloom_main/issues/297)-[#306](https://github.com/ogirkoviylord/folioloom_main/issues/306)
PR-sized implementation breakdown.

This note is docs-only architecture discovery. It does not implement code,
database schema or state changes, runtime `var/` operations, environment or
deployment changes, provider behavior changes, secrets handling, admin control
changes, or user-facing UX changes.

This note does not close Gate B and does not claim beta, release, or production
readiness.

## Routing Receipt

- Classification: docs-only architecture task.
- Risk level: high for future implementation because scheduler state,
  provider capacity, retries, cost caps, kill switch behavior, and user fairness
  are high-risk areas.
- Primary repo-level skill: `docs-sync`, limited to this approved docs-only
  architecture note update.
- Supporting route: `architecture-review` concepts were applied because the
  subject is cross-component scheduler/provider architecture.
- Approval status: approved only for this docs-only note. Future scheduler,
  database/schema/state, provider behavior, deployment, secrets/env, runtime
  data, admin control, or user-facing UX changes require explicit owner
  approval.
- Verification plan for this note: docs-only review plus `git diff --check`.

## Problem

FolioLoom needs smart multichannel scheduling that preserves provider
multichannel capacity while protecting book/manuscript quality, ETA stability,
cost caps, kill switch behavior, retries, provider-failure handling, scheduler
leases, user fairness, and future growth in provider keys/workers.

The desired behavior is:

- when the queue is small, one translation may use available capacity;
- when the queue grows, newly available slots are redistributed fairly between
  jobs and users;
- active provider calls are not interrupted unless there is a strong future
  safety reason and explicit approval;
- Redis must not become a scheduler correctness dependency without a strong
  reason because PostgreSQL is already the scheduler source of truth.

## Confirmed Facts

- PostgreSQL is the source of truth for production scheduler correctness:
  job state, work-unit state, leases, attempts, retries, cancellation, resume,
  and worker heartbeats are intended to converge on PostgreSQL.
- The existing production scheduler design treats Redis, `LISTEN/NOTIFY`, or an
  outbox as optional wake-up layers only; PostgreSQL due-row scanning must
  remain sufficient for recovery.
- The current scheduler already has durable work-unit claiming concepts:
  worker leases, claim tokens, caps, retries, and scheduler events.
- Provider key/channel metadata already includes capacity-related concepts such
  as weight and `max_parallel_requests`.
- Current provider channel throttling and key selection are process-local.
  They are useful for one worker process but are not enough by themselves for
  multi-worker correctness.
- Gate B remains open. Issue #80 captured scheduler/runtime/provider capacity
  consistency discovery. Issues #297-#306 now track the PR-sized path from this
  docs-only contract through durable provider-slot leases, fair queue policy,
  ETA/backpressure inputs, optional wake-up hints, and scale validation.
- Free closed beta is not launched according to current project documents.

## Assumptions

- The near-term provider count is about eight keys/channels and may grow later.
- The first closed-beta capacity target favors correctness, safety, and
  diagnosability over maximum throughput.
- Most provider capacity changes can wait for a provider call boundary.
- Per-job parallelism should remain conservative by default because long-book
  translation quality can suffer when too many chunks are translated in
  parallel without enough surrounding quality controls.
- Existing in-process adaptive throttle can remain as a local health signal,
  but should not own distributed correctness.

## Unknown

- Unknown: the exact provider identity model that should be persisted for
  env-provided keys without exposing secrets or unstable secret ids.
- Unknown: whether provider slot leases should be one row per physical key,
  per logical channel, or per weighted virtual slot.
- Unknown: the best initial per-job parallel cap for real beta documents across
  TXT, DOCX, and EPUB.
- Unknown: whether bot-side preview calls currently share enough of the worker
  provider-capacity path to be covered by the same future lease model.
- Unknown: real provider rate-limit behavior under multiple workers and many
  keys without approved provider-load evidence.
- Unknown: current CI status for this branch unless checked on GitHub.

## TBD

- TBD: owner approval for any database schema/state change that adds durable
  provider-slot lease rows.
- TBD: owner approval for any scheduler/provider behavior change.
- TBD: owner approval for any real provider-load verification.
- TBD: owner decision on whether provider capacity should be configured as
  physical slots, weighted virtual slots, or both.
- TBD: owner decision on when ETA/progress UX should expose smart scheduling
  estimates to users.
- TBD: owner decision on whether any emergency preemption policy is ever
  allowed for active provider calls. The current recommendation is no
  preemption.

## Executive Verdict

Recommended architecture:

1. Keep PostgreSQL as the correctness layer.
2. Add PostgreSQL provider-slot leases as the future durable capacity contract.
3. Treat Redis only as an optional wake-up/notification accelerator.
4. Use an operational single-worker or conservative-capacity constraint as the
   interim safety position until provider-slot leases are implemented and
   evidenced.
5. Add smart elastic fairness only after the correctness layer exists.
6. Never interrupt already-started provider calls in the normal scheduler.
   Capacity changes and fairness rebalancing should apply to future slot
   acquisition only.

This matches the current architecture better than a Redis semaphore because it
keeps job/work-unit/provider-capacity decisions in one durable source of truth.

## Chosen Method In Detail

The chosen method is PostgreSQL-backed provider-slot leases plus fair
scheduling on top of those leases.

The first implementation layer should not try to be a clever scheduler. It
should make provider capacity distributed and durable. A worker may start a
provider call only after PostgreSQL records that the worker owns both:

1. a work-unit lease for the specific book/manuscript fragment;
2. a provider-slot lease for the specific provider slot that will execute the
   call.

This matters because theoretical capacity such as `8 keys * 2 slots = 16`
does not automatically mean safe capacity. With process-local key pools, each
worker process can see its own `active_requests` and conclude that a channel
has room. Two or more workers can therefore overestimate the same provider
capacity unless slot ownership is recorded in a shared durable journal.

### Slot Model

Each provider key or channel is expanded into logical slots. For example, a
channel `deepseek/key-a` with `max_parallel_requests=2` becomes:

- `deepseek/key-a/slot-0`;
- `deepseek/key-a/slot-1`.

The lease row should identify the safe provider id, safe channel id, logical
slot index, job id, work-unit id, worker id and work-unit claim token. It must
never store raw API keys, raw document text, prompts, translations, provider
payloads or unredacted stack traces.

Key-level slots are not enough by themselves. An account/model-level cap should
sit above them. If the key-level inventory says `16` theoretical slots but the
provider account or model should safely run only `10`, the effective available
capacity is `10`. This higher cap protects provider reliability, cost control
and future model/account limits without changing the logical key-slot model.

### Worker Flow

The future worker/provider flow should be:

1. check kill switch and beta/cost caps before new provider work;
2. select the next eligible work unit using scheduler policy;
3. acquire the work-unit lease in PostgreSQL;
4. acquire a compatible provider-slot lease in PostgreSQL;
5. start the provider call only after both leases exist;
6. complete or fail the work unit with the claim token;
7. release the provider-slot lease with a safe release reason;
8. let expired leases recover through the same durable scheduler maintenance
   path.

If either lease cannot be acquired, the provider call must not start. The
worker can sleep, retry later, or move on to another eligible unit according to
the approved scheduler contract.

### Why This Is The Best Fit

This method is the best fit because it extends the architecture FolioLoom
already has instead of replacing it. PostgreSQL already owns production
scheduler correctness for jobs, work units, claim tokens, retries, cancellation
and worker recovery. Provider-slot leases add the missing sibling contract:
durable ownership of external provider capacity.

It is better than a Redis semaphore because Redis would split correctness
between two systems. Redis can be useful later as a wake-up signal, but
PostgreSQL must remain sufficient to reconstruct the queue and capacity state
after crashes or restarts.

It is better than pure process-local key pools because process-local
`active_requests` only protects one process. It cannot prove that all workers
together are below provider capacity.

It is better than starting with weighted fair queueing or deficit round robin
because those policies answer who should get the next slot, not whether the
slot is globally safe to use. Fairness should sit on top of durable slot
ownership.

It is better than ETA-aware scheduling as a first change because ETA should be
derived from durable state, retry pressure and observed throughput. ETA should
not become the mechanism that protects provider correctness.

### Fairness Boundary

Provider capacity and queue policy must stay separate:

- provider capacity decides whether a safe slot exists;
- queue policy decides which eligible job or user receives the next free slot.

When the queue is small, one job may use spare capacity within approved caps.
When competing jobs or users appear, newly available slots are redistributed
according to fairness policy. Already-started provider calls are not preempted.
Fairness applies only at future slot acquisition boundaries.

The first fairness layer should be simple and auditable: conservative per-job
parallel caps plus per-user/job fairness. Weighted fair scheduling or deficit
round robin can follow once the slot lease layer is working and tests show the
distribution behavior.

## Proposed Correctness Layer

Add a future PostgreSQL provider-slot lease model. This is not implemented by
this note.

Conceptual lease fields:

- provider id, such as `deepseek`;
- safe provider channel id or safe virtual slot id;
- optional key fingerprint or key metadata id, never a raw key;
- job id;
- work-unit id;
- worker id;
- work-unit claim token;
- lease status;
- lease acquired timestamp;
- lease expiry timestamp;
- released timestamp;
- safe failure category or release reason.

The row must not contain:

- raw API keys;
- raw document text;
- prompts;
- translations;
- provider request/response payloads;
- unredacted stack traces;
- unsafe user data.

The worker claim path should eventually acquire both:

1. a work-unit lease;
2. a provider-slot lease.

If either lease cannot be acquired, the worker must not start a provider call
for that work unit. Lease release happens when the provider call completes,
fails, is safely retried, or expires through existing recovery logic.

## Scheduling Policy

Initial policy:

- enforce global, per-user, per-job, and provider-slot caps before starting new
  provider work;
- allow one job to consume spare capacity only while there is no competing
  eligible work;
- when more jobs enter the queue, redistribute only newly available slots;
- preserve cooperative cancellation: do not start new units after cancellation,
  but let in-flight provider calls finish or expire through leases;
- keep retries bounded and auditable;
- keep cost caps and kill switch checks in front of new work;
- keep raw text and provider secrets out of logs/admin/telemetry/artifacts.

Future smart policy:

- evaluate weighted fair scheduling or deficit round robin at provider-slot
  acquisition time, but implement it only when observed or simulated queue
  evidence shows the simple fair policy is too crude;
- keep a per-job maximum parallel cap for book/manuscript quality;
- let priority aging avoid starvation;
- let adaptive throttle lower effective capacity for unhealthy channels without
  becoming the source of distributed correctness;
- keep ETA/progress estimates based on observed throughput and queue position,
  not on optimistic maximum capacity.

## Issue #303 Fairness Upgrade Decision

Issue #303 should keep the simple `least_active_user_job_v1` policy from issue
#302 and defer DRR/WFQ for now.

Decision status: proposed PR-ready recommendation until accepted by the owner
or merged through the normal PR workflow.

Why:

- the simple policy already separates queue policy from provider capacity;
- it prevents a large job from taking every newly free slot while other jobs are
  waiting;
- it supports conservative per-job and per-user caps without adding persisted
  policy state;
- active provider calls remain non-preemptive;
- retries and backoff remain governed by work-unit state rather than by a
  separate fairness ledger;
- there is no current repository evidence showing that weighted fairness,
  deficits, token estimates or paid/free priority tiers are needed before ETA
  and backpressure diagnostics exist.

Deferred upgrade trigger:

- real or simulated queue evidence shows starvation or poor distribution that
  the simple policy cannot explain or fix;
- work-unit cost estimates become reliable enough to justify token/page-based
  fairness;
- the owner approves any required scheduler behavior, persisted policy state,
  admin diagnostics, ETA/UX, pricing/payment priority, or deployment/runtime
  changes.

This decision does not change provider-slot leases, provider capacity caps,
Redis wake-up scope, ETA/user-facing UX, payment priority, deployment/runtime
behavior, Gate B status, free beta status, or production readiness.

## Brainstormed Options

### 1. PostgreSQL Provider-Slot Leases

What it solves:

- multi-worker correctness for provider capacity;
- crash recovery through durable leases;
- one source of truth for work-unit and provider-slot ownership;
- metadata-only auditability for Gate B evidence and admin diagnostics.

Where it breaks:

- requires schema/state design and migration approval;
- bad lease expiry tuning can underuse capacity or allow stale slots to linger;
- provider identity for env keys must be designed carefully.

Required approvals:

- database schema/state;
- scheduler behavior;
- provider behavior if acquisition changes call timing;
- admin diagnostics if surfaced.

Implementation complexity: medium-high.
Rollback complexity: medium if feature-gated; high if mixed with unrelated
scheduler rewrites.

### 2. Redis Semaphore

What it solves:

- simple distributed counting semaphore;
- fast slot acquire/release;
- natural wake-up integration.

Where it breaks:

- Redis becomes a correctness dependency unless carefully demoted to a hint;
- split-brain risk with PostgreSQL work-unit leases;
- crash recovery and audit history become harder;
- rollback is risky if workers rely on Redis state.

Required approvals:

- scheduler behavior;
- deployment/runtime dependency behavior;
- possibly Redis persistence/operations policy.

Implementation complexity: medium.
Rollback complexity: medium-high.

### 3. Operational Single-Worker Constraint

What it solves:

- safest interim path while Gate B is open;
- avoids distributed provider-slot contention;
- easy to reason about with current process-local key pool.

Where it breaks:

- does not scale with more workers;
- underuses capacity as key count grows;
- relies on operational discipline instead of durable enforcement.

Required approvals:

- deployment/runtime approval if changing worker counts or runtime settings.

Implementation complexity: low.
Rollback complexity: low.

### 4. Conservative Capacity Caps

What it solves:

- reduces provider/cost risk while capacity evidence is incomplete;
- protects manuscript quality by limiting per-job parallelism;
- can be applied before smarter fairness.

Where it breaks:

- lower throughput and less attractive ETAs;
- does not solve multi-worker provider correctness alone.

Required approvals:

- scheduler/runtime setting approval if changing active caps.

Implementation complexity: low.
Rollback complexity: low.

### 5. Weighted Fair Scheduling

What it solves:

- fair allocation across users/jobs when queue depth grows;
- supports future paid/free priority or owner-selected weights;
- improves starvation resistance.

Where it breaks:

- fairness math can be wrong without durable provider-slot ownership;
- can destabilize ETAs if weights change frequently;
- may reduce throughput if applied too rigidly.

Required approvals:

- scheduler behavior;
- user fairness policy if externally visible;
- ETA/UX approval if exposed.

Implementation complexity: medium.
Rollback complexity: medium.

### 6. Elastic Burst Scheduling

What it solves:

- lets one translation use spare capacity when the queue is empty or light;
- improves completion time for isolated jobs;
- works well with future provider-slot leases.

Where it breaks:

- can monopolize capacity without per-job/user caps;
- can hurt long-form quality if too many chunks run in parallel;
- creates unstable ETAs if burst capacity is treated as guaranteed.

Required approvals:

- scheduler behavior;
- provider behavior/cost risk review.

Implementation complexity: medium.
Rollback complexity: medium.

### 7. Token Bucket

What it solves:

- rate-limit smoothing for provider requests;
- useful for cost/rate-limit guardrails;
- can absorb provider-specific burst rules.

Where it breaks:

- controls request rate, not distributed slot ownership;
- does not prevent duplicate capacity claims across workers by itself;
- token refill policy can be difficult to match to provider behavior.

Required approvals:

- provider behavior;
- cost/cap policy if token rates affect spend.

Implementation complexity: medium.
Rollback complexity: medium.

### 8. Deficit Round Robin / Weighted Fair Queueing

What it solves:

- fair scheduling with variable work-unit cost;
- can account for estimated tokens/pages rather than unit count only;
- better long-queue behavior than naive round-robin.

Where it breaks:

- needs reliable cost estimates;
- harder to explain in admin diagnostics;
- should not be the first correctness layer.

Required approvals:

- scheduler behavior;
- ETA/progress UX if surfaced.

Implementation complexity: medium-high.
Rollback complexity: medium.

### 9. Per-Job Max Parallel Cap

What it solves:

- protects book/manuscript consistency;
- prevents one large document from consuming every slot;
- gives a simple fairness control independent of provider count.

Where it breaks:

- too low a cap hurts throughput;
- too high a cap hurts quality and fairness;
- cap values need evidence from real documents.

Required approvals:

- scheduler behavior;
- quality policy decision for initial cap.

Implementation complexity: low-medium.
Rollback complexity: low-medium.

### 10. Adaptive Throttle

What it solves:

- reacts to provider failures and rate limits;
- reduces effective capacity for unhealthy channels;
- improves retry/provider-failure handling.

Where it breaks:

- process-local throttle is not distributed correctness;
- distributed throttle state adds complexity and state approval needs;
- too aggressive throttle can starve valid keys.

Required approvals:

- provider behavior;
- scheduler behavior if throttle changes claim eligibility.

Implementation complexity: medium.
Rollback complexity: medium.

### 11. Hybrid: PostgreSQL Leases + Optional Redis Wake-Up + Fair Policy

What it solves:

- combines durable correctness with faster wake-ups and future smart fairness;
- allows Redis failure without correctness loss;
- gives a phased path from conservative beta safety to scaled workers/keys.

Where it breaks:

- more moving parts;
- requires strict boundaries so Redis never becomes authoritative;
- observability must show PostgreSQL lease state first.

Required approvals:

- database schema/state;
- scheduler behavior;
- provider behavior;
- deployment/runtime approval only if enabling Redis wake-up changes runtime.

Implementation complexity: high, but can be phased.
Rollback complexity: medium if each layer is feature-gated.

## Scorecard

Scores: 1 = weak fit, 5 = strong fit.

| Option | Correctness across bot + worker + multiple workers | More keys/workers | Gate B risk | Book/manuscript quality | ETA stability | Cost/cap/kill-switch safety | Observability/admin diagnostics | Fit with current PostgreSQL scheduler |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PostgreSQL provider-slot leases | 5 | 5 | 3 | 4 | 4 | 5 | 5 | 5 |
| Redis semaphore | 3 | 4 | 2 | 3 | 3 | 3 | 3 | 2 |
| Single-worker constraint | 3 | 1 | 5 | 4 | 3 | 4 | 2 | 4 |
| Conservative capacity caps | 2 | 2 | 5 | 5 | 3 | 5 | 3 | 4 |
| Weighted fair scheduling | 3 | 4 | 3 | 4 | 4 | 4 | 4 | 4 |
| Elastic burst scheduling | 3 | 5 | 2 | 3 | 3 | 3 | 3 | 4 |
| Token bucket | 2 | 3 | 3 | 3 | 3 | 4 | 3 | 3 |
| DRR/WFQ | 4 | 5 | 2 | 4 | 4 | 4 | 3 | 4 |
| Per-job max parallel cap | 3 | 3 | 4 | 5 | 4 | 4 | 4 | 5 |
| Adaptive throttle | 2 | 3 | 3 | 4 | 3 | 4 | 4 | 3 |
| Hybrid phased architecture | 5 | 5 | 4 | 5 | 4 | 5 | 5 | 5 |

Interpretation:

- Highest near-term safety: single-worker or conservative caps.
- Best correctness layer: PostgreSQL provider-slot leases.
- Best long-term architecture: PostgreSQL provider-slot leases plus fair
  elastic scheduling and optional Redis wake-up.
- Highest risk if used as correctness source: Redis semaphore without
  PostgreSQL-backed ownership.

## Recommended Architecture

Use a phased hybrid architecture:

1. Interim constraint: keep worker/provider capacity conservative while Gate B
   is open. Operationally prefer one worker or caps low enough that current
   process-local provider capacity cannot oversubscribe provider calls.
2. Correctness layer: add PostgreSQL provider-slot leases and require workers
   to acquire a provider slot before starting a provider call.
3. Smart layer: add per-job max parallel caps, weighted fairness or DRR/WFQ,
   and elastic burst rules that apply only when slots become newly available.
4. Wake-up layer: optionally use Redis, `LISTEN/NOTIFY`, or an outbox to wake
   workers, but keep PostgreSQL due rows and provider-slot leases
   authoritative.
5. Health layer: keep adaptive throttling as provider-health input that lowers
   effective capacity, not as the distributed ownership mechanism.

This preserves multichannel scheduling while preventing correctness from
depending on process-local counters or Redis-only state.

## Rejected Alternatives

- Redis as authoritative semaphore: rejected for now because it would split
  scheduler correctness between PostgreSQL and Redis.
- Pure process-local key pool with more workers: rejected as the target
  architecture because each process can overestimate available provider slots.
- Immediate high parallelism across all keys: rejected while Gate B is open
  because it increases provider failure, cost, and manuscript-quality risk.
- Preempting active provider calls for fairness: rejected for normal operation
  because it wastes cost, creates retry ambiguity, and complicates quality and
  user progress semantics.
- DRR/WFQ as the first change: rejected as first layer because fairness
  algorithms should sit on top of durable slot ownership, not replace it.

## Phased Plan

### Phase 0: Issues #80 And #297 Docs-Only Contract

Goal:

- preserve the issue #80 discovery evidence and gaps;
- finalize issue #297 as the implementation-ready architecture contract;
- keep capacity conservative until the durable correctness layer is built;
- document the proposed architecture without changing code.

Scope:

- metadata-only evidence;
- focused tests or review for current scheduler/provider capacity behavior;
- no provider-load run without approval;
- no schema/state/provider behavior changes.

Exit criteria:

- issue #297 records the implementation-ready contract, dependencies and
  approval gates for #298-#306;
- any remaining issue #80 evidence gaps stay recorded honestly as `Unknown` or
  follow-up work.

### Phase 1: Correctness Layer

Goal:

- implement PostgreSQL provider-slot leases behind explicit approval.

Scope:

- durable slot ownership;
- lease acquire/release/expiry;
- worker claim integration;
- safe metadata-only events;
- tests for multiple workers and stale leases.

Out of scope:

- user-facing ETA changes;
- high-throughput provider-load tests without separate approval;
- Redis correctness dependency.

### Phase 2: Smart Elastic Fair Scheduling

Goal:

- allow spare capacity to be used by one job while fairly redistributing newly
  available slots when the queue grows.

Scope:

- per-job max parallel cap;
- user/job fairness;
- evaluation of weighted fair scheduling or DRR/WFQ, with implementation
  deferred until evidence shows the simple policy is insufficient;
- adaptive throttle as capacity input;
- starvation and retry tests.

Out of scope:

- preempting active provider calls;
- paid priority policy unless separately approved.

### Phase 3: ETA And Progress UX

Goal:

- make progress and ETA reflect real queue position, lease ownership, observed
  throughput, retries, and throttling.

Scope:

- backend metadata model for ETA inputs;
- admin/operator diagnostics;
- future user-facing copy only after explicit UX approval.

Out of scope:

- public production claims;
- exposing provider internals or secrets.

Issue #304 implementation boundary:

- add an internal `SchedulerBackpressureDiagnostics` /
  `SchedulerEtaEstimate` input model;
- derive queue depth, eligible waiting work, retry pressure, active work-unit
  leases, provider-slot capacity pressure and recent throughput from durable
  scheduler state and safe provider-capacity diagnostics;
- return `Unknown` when throughput or capacity evidence is insufficient;
- keep this as read-only metadata for diagnostics and future UX work;
- do not add user-facing ETA copy, admission rejection, Redis wake-up,
  payment priority, deployment/runtime/env/secrets changes, runtime data
  operations, Gate B claims or release-readiness claims in this slice.

### Phase 4: More Keys And Workers

Goal:

- scale safely beyond the initial key count and one worker.

Scope:

- multi-worker provider-slot correctness tests;
- approved provider-load smoke only if owner permits;
- operational diagnostics for slot usage, stale leases, throttled channels,
  retry pressure, and cap/kill-switch behavior.

Out of scope:

- deployment changes without approval;
- runtime `var/` changes without approval;
- paid/public launch readiness claims.

## Implementation Issue Dependency Order

These are the active PR-sized issues for the approved smart multichannel
direction. One issue should produce one focused PR. Later issues may be
re-scoped by the owner, but the ordering below is the safe default because it
builds correctness before fairness and scale.

1. [#297](https://github.com/ogirkoviylord/folioloom_main/issues/297):
   finalize this docs-only provider-slot lease design. No code, schema, runtime
   data, env, deployment, admin, provider behavior, or UX changes.
2. [#298](https://github.com/ogirkoviylord/folioloom_main/issues/298):
   add PostgreSQL provider-slot inventory and lease primitives. Depends on
   #297 and requires database schema/state approval before implementation.
3. [#299](https://github.com/ogirkoviylord/folioloom_main/issues/299):
   require a provider-slot lease before scheduled provider calls. Depends on
   #297 and #298, and requires scheduler/provider behavior approval.
4. [#300](https://github.com/ogirkoviylord/folioloom_main/issues/300):
   add account/model-level provider capacity caps above key-level slots.
   Depends on #297-#299.
5. [#301](https://github.com/ogirkoviylord/folioloom_main/issues/301):
   add safe metadata-only provider-capacity diagnostics. Depends on
   #297-#300 and requires admin/scheduler diagnostics approval if an admin
   surface changes.
6. [#302](https://github.com/ogirkoviylord/folioloom_main/issues/302):
   add the first simple fair queue policy for newly free provider slots.
   Depends on #297-#301.
7. [#303](https://github.com/ogirkoviylord/folioloom_main/issues/303):
   evaluate and optionally upgrade fairness to DRR/WFQ. Depends on #302 and
   should be deferred or closed as keep-simple if #302 is sufficient.
8. [#304](https://github.com/ogirkoviylord/folioloom_main/issues/304):
   add internal backpressure and ETA input model. Depends on #297-#302 and must
   not add user-facing ETA promises without separate UX approval.
9. [#305](https://github.com/ogirkoviylord/folioloom_main/issues/305):
   add optional wake-up notifications without Redis correctness dependency.
   Depends on #297-#300 and #302. Workers must re-read PostgreSQL after every
   wake-up.
10. [#306](https://github.com/ogirkoviylord/folioloom_main/issues/306):
    validate scaling across keys, logical slots and workers. Depends on the
    correctness/fairness/diagnostics layers above, and on #305 only if wake-up
    notifications are part of the scale path.

PR-ready for any implementation issue means:

- the issue scope and acceptance criteria are implemented without expanding
  into later issues;
- required approvals are recorded before touching gated areas;
- focused tests and required broader checks are run or honestly reported as
  unavailable;
- reviewer pass checks scope, tests, safety/privacy/payment/deployment
  guardrails, docs drift and release-readiness claims;
- no issue claims Gate B, free beta, release or production readiness.

## Risks And Approval Gates

Relevant risks:

- R-005: core workflow instability;
- R-011: background jobs/scheduler races;
- R-019: external integrations/provider failures;
- R-025: provider cost/cap risk;
- R-032: cross-component conflict zones.

Approval gates before future implementation:

- database schema/state changes;
- scheduler/job/work-unit/provider-slot state changes;
- provider behavior changes;
- deployment/runtime/worker-count changes;
- secrets/env handling;
- admin/control or diagnostic surfaces;
- user-facing progress/ETA UX;
- real provider-load tests;
- runtime `var/` data operations.

