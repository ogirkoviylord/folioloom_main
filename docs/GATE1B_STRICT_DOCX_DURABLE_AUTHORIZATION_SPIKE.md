# Gate 1B strict DOCX durable authorization: implementation-readiness spike

**Date:** 2026-07-23

**Status:** readiness packet for architecture critique; no runtime/schema/migration change approved by this document
**Scope:** new strict DOCX jobs only; no legacy `with_glossary` fallback change

## 1. Goal and approved policy

This document maps the exact repository seams required to implement the owner-approved Gate 1B policy:

- DOCX-only and new strict jobs only;
- durable `glossary_approval` plus an immutable strict-job binding;
- Guard A: strict admission before job/work-unit database inserts;
- Guard B: atomic binding-consistency eligibility before claim-state mutation;
- dedicated runtime-readable opaque snapshot custody/reference;
- approval/job records and scheduler evidence remain metadata-only;
- no source-byte immutability claim without object-store conditional-version evidence;
- legacy automatic `with_glossary` fallback is unchanged.

This is a design packet, not approval to change database schema/state, scheduler behavior, storage, providers, Telegram, or deployment.

## 2. Classification and boundaries

- **Task type:** spike/discovery and docs-only.
- **Risk level:** high: persistent schema/state plus scheduler claim semantics.
- **In scope:** additive persistent authorization model, strict admission/claim transactions, custody interface, migration sequencing, and verification design.
- **Out of scope:** TXT/EPUB, legacy jobs, automatic glossary fallback, object-store immutability/versioning claims, deletion/TTL/cleanup policy, provider calls, Telegram/server work, cache-key behavior, UI/auth redesign, data migration/cleanup, PR/issue creation.

## 3. Confirmed repository facts

### 3.1 Current stores and schema ownership

- SQLite is `SQLiteTranslationJobStore` in `src/translator_service/persistent_jobs.py`. Its constructor calls `_create_schema()`; the current compatibility mechanism is additive `CREATE TABLE IF NOT EXISTS` plus `_ensure_column(...)` using `PRAGMA table_info` (`persistent_jobs.py:166-175`, `1420-1573`, `1909-1925`).
- PostgreSQL is `PostgresSchedulerStore` in `src/translator_service/postgres_scheduler.py`. Its schema is the `SCHEMA_SQL` string, initialized by `initialize_postgres_scheduler_schema()` on store open (`postgres_scheduler.py:61-196`, `372-378`; `persistent_job_store.py:75-91`). There is no separate versioned migration framework in the opened source.
- SQLite and PostgreSQL have the same core tables: `translation_jobs`, `work_units`, `work_unit_attempts`, `scheduler_events`, and `worker_heartbeats`. PostgreSQL additionally has provider-slot tables.
- Important divergence: PostgreSQL `translation_jobs` already has `cancel_requested_at` and `resume_blocked_reason`, which SQLite does not. SQLite timestamps are TEXT; PostgreSQL uses `TIMESTAMPTZ`.
- The public `PersistentJobStore` protocol currently exposes `create_job()` and `add_work_units()` separately, and does not expose scheduler-claim or strict-admission APIs (`persistent_job_store.py:16-66`). Its planner annotations currently name `SQLiteTranslationJobStore` directly (`persistent_planner.py:50-68`, `128-147`).

### 3.2 Existing non-atomic admission seam

- `create_persistent_docx_job_plan()` first reads and parses the DOCX, calls `store.create_job(...)`, creates intermediate stored work-unit objects, then calls `store.add_work_units(...)` (`persistent_planner.py:128-201`, `413-439`).
- Therefore the existing job and work-unit insertion is split across two store transactions. It cannot prove the required all-or-nothing strict admission.
- It also writes intermediate object-store units after job creation but before `add_work_units`. The approved Guard A only mandates refusal before job/work-unit *inserts*; object-store compensation/lifecycle is a separate unresolved design concern and must not be silently claimed atomic with the database.
- `translation_policy` is generic JSON built in `_translation_policy_snapshot()` and currently receives `glossary_mode` and `prepared_glossary_package` (`persistent_planner.py:301-350`). It is not an acceptable location for raw approved glossary material in the strict design.

### 3.3 Existing claim seams

- SQLite scheduled claim is `SQLiteTranslationJobStore.claim_next_scheduled_work_unit()` (`persistent_jobs.py:544-825`). It selects an eligible row, then conditionally updates `work_units`, then updates the job status and inserts `work_unit_claimed` event.
- PostgreSQL scheduled claim is `PostgresSchedulerStore.claim_next_scheduled_work_unit()` and `_CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL` (`postgres_scheduler.py:219-369`, `546-623`). It uses a transaction-scoped advisory lock, candidate CTE, `FOR UPDATE ... SKIP LOCKED`, then updates the unit; only after a returned row does it update job status and add the event.
- Worker and scheduler runner call the store claim before loading a source object, acquiring provider capacity, running glossary hooks, or invoking a provider (`worker.py:723-814`; `scheduler_runner.py:249-358`). Guard B must therefore be in the store claim predicate, not in a later worker preflight.
- Existing retry/requeue/recovery all return units to claimable statuses (`failed`, `failed_retryable`, or `pending`) and claim paths include those statuses. The strict predicate must be applied on every such claim, not only the first claim.

## 4. Proposed durable model (additive and versioned)

The following is a coder-ready proposed shape. Names remain subject to the required architecture critiques.

### 4.1 Tables

Use dedicated tables instead of generic JSON columns:

```text
glossary_snapshot_custody
- custody_id TEXT primary key
- snapshot_ref TEXT NOT NULL UNIQUE        # opaque runtime-readable storage reference
- snapshot_digest TEXT NOT NULL             # digest/identity, not snapshot content
- snapshot_schema_version INTEGER NOT NULL
- created_at <backend timestamp>
- retention_mode TEXT NOT NULL DEFAULT 'retain'
- CHECK retention_mode = 'retain'           # no cleanup behavior in this slice

glossary_approvals
- approval_id TEXT primary key
- custody_id TEXT NOT NULL REFERENCES glossary_snapshot_custody(custody_id)
- snapshot_digest TEXT NOT NULL
- approval_schema_version INTEGER NOT NULL
- approval_status TEXT NOT NULL             # only 'approved' is eligible
- approved_at <backend timestamp>
- created_at <backend timestamp>
- UNIQUE(custody_id, snapshot_digest, approval_schema_version)

strict_job_glossary_bindings
- job_id TEXT primary key REFERENCES translation_jobs(id)
- approval_id TEXT NOT NULL REFERENCES glossary_approvals(approval_id)
- custody_id TEXT NOT NULL REFERENCES glossary_snapshot_custody(custody_id)
- snapshot_digest TEXT NOT NULL
- binding_schema_version INTEGER NOT NULL
- created_at <backend timestamp>
```

Rationale:

- `strict_job_glossary_bindings.job_id` is the immutable one-to-one strict-job binding. Do not add a mutable `is_strict` Boolean to generic job JSON.
- `approval_id` and `custody_id` give FK-backed relational identity. Repeating `snapshot_digest` is intentional denormalized binding evidence and must be checked against both referenced rows in Guard B.
- The custody table stores only an opaque `snapshot_ref` plus metadata/digest. The approved glossary snapshot bytes/content stay behind a dedicated custody reader, never in `translation_policy`, `scheduler_events.payload_json`, attempts, logs, or generic job metadata.
- Do not add a row for legacy jobs. Absence of a binding means legacy semantics, not strict denial.

### 4.2 Runtime-readable custody interface

Introduce a narrow interface outside scheduler JSON/event paths:

```text
GlossarySnapshotCustody
  store_approved_snapshot(snapshot) -> CustodyReference
  read_approved_snapshot(snapshot_ref) -> GlossarySnapshot
  verify_reference(custody_id, snapshot_ref, snapshot_digest) -> verified/denied
```

`CustodyReference` must contain opaque identity/metadata only (`custody_id`, `snapshot_ref`, digest, schema version). `read_approved_snapshot` is called only after claim has atomically succeeded and before glossary context rendering/provider work. A missing, unreadable, invalid, or digest-mismatched snapshot is a runtime failure path for an already-claimed strict unit; it is not a reason to weaken Guard B.

Retention is **default retain / no cleanup**. No deletion API, TTL, object deletion, or cleanup job is part of this slice. Any future deletion/rewrite policy requires a separate owner decision and risk review.

## 5. Required store and planner API changes

### 5.1 New strict admission request/result

Add backend-parity types, preferably in the persistent-store contract rather than the planner:

```text
StrictDocxAdmissionRequest
- job fields now supplied to create_job
- work_unit_plans: sequence/source hashes/opaque source-object keys
- approval_id, custody_id, snapshot_digest
- approval_schema_version, binding_schema_version
- strict_schema_version

StrictAdmissionResult
- admitted: bool
- denial_code: strict_schema_unavailable | approval_missing | approval_not_approved |
  approval_binding_mismatch | document_kind_not_docx | invalid_request
- job/work_units only when admitted
```

The exact external caller must prepare/validate the DOCX plan and obtain the approved custody reference before invoking the store. It must not pass raw snapshot material to the store.

### 5.2 One atomic operation

Add `admit_strict_docx_job(request) -> StrictAdmissionResult` to both store implementations and `PersistentJobStore` protocol. It replaces the strict path's `create_job()` + `add_work_units()` split; legacy planner functions retain their current split behavior.

Inside **one database transaction**, in this order:

1. Validate `document_kind == 'docx'`, required schema/version values, nonempty/ordered work-unit plan, and opaque request shape. On failure: return typed denied result before any database write.
2. Lock/read the requested `glossary_approvals` and custody row; require `approval_status='approved'`, matching `custody_id`, matching digest, and supported schema versions. On failure: typed denial and rollback/no write.
3. Insert exactly one `translation_jobs` row.
4. Insert one immutable `strict_job_glossary_bindings` row for that job.
5. Insert all work-unit rows.
6. Commit and return job/work units.

No scheduler event, attempt, lease, or provider-slot record is inserted by admission. The new binding row is the durable evidence; admission audit metadata, if any, must be a dedicated metadata-only table and is optional for this narrow slice.

SQLite implementation must use a transaction that obtains a write lock before the approval read (for example an explicit `BEGIN IMMEDIATE` on a dedicated/appropriately serialized connection) so the check and inserts are one atomic unit. The existing `with self._connection:` pattern alone is insufficiently explicit for the new concurrency contract.

PostgreSQL implementation must lock the approval/custody rows (`SELECT ... FOR KEY SHARE` or stronger only when justified) in the same `connection.transaction()` that inserts job, binding, and units. FK checks and a unique `job_id` binding make a second binding impossible.

### 5.3 Caller placement

Add a distinct `create_persistent_strict_docx_job_plan(...)` or equivalent strict branch in `persistent_planner.py`. It must:

1. reject non-DOCX before generating a strict request;
2. parse/plan DOCX and construct work-unit plans;
3. call custody preparation through the dedicated interface;
4. call `admit_strict_docx_job()` once;
5. return a typed refusal without `create_job()` / `add_work_units()` calls when refused.

The existing `create_persistent_docx_job_plan()` stays legacy-compatible; do not alter TXT/EPUB or `with_glossary` automatic paths.

## 6. Guard B: exact claim predicate and no-side-effect denial

### 6.1 Eligibility rule

For a candidate `wu` / `tj`, it is strict only when a row exists in `strict_job_glossary_bindings b` for `b.job_id=tj.id`. A strict candidate is eligible only if a single relational check proves all of the following:

```text
b.approval_id -> glossary_approvals a
b.custody_id  -> glossary_snapshot_custody c
a.approval_status = 'approved'
a.custody_id = b.custody_id
b.snapshot_digest = a.snapshot_digest = c.snapshot_digest
b.binding_schema_version and a/c schema versions are supported
c.retention_mode = 'retain'
```

An absent binding remains eligible as a legacy job. A present but inconsistent/missing/unsupported binding is not eligible. Do not attempt to repair, cancel, mark failed, event-log, lease, or update such a job inside claim.

### 6.2 SQLite placement

Add this exact logical predicate to **both** places in `SQLiteTranslationJobStore.claim_next_scheduled_work_unit()`:

1. the candidate `SELECT` at `persistent_jobs.py:567-686`; and
2. the conditional `UPDATE work_units ... WHERE` at `persistent_jobs.py:694-779`.

Use a `NOT EXISTS` predicate shaped as:

```sql
AND NOT EXISTS (
  SELECT 1
  FROM strict_job_glossary_bindings b
  LEFT JOIN glossary_approvals a ON a.approval_id = b.approval_id
  LEFT JOIN glossary_snapshot_custody c ON c.custody_id = b.custody_id
  WHERE b.job_id = wu.job_id
    AND (
      a.approval_id IS NULL
      OR c.custody_id IS NULL
      OR a.approval_status <> 'approved'
      OR a.custody_id <> b.custody_id
      OR a.snapshot_digest <> b.snapshot_digest
      OR c.snapshot_digest <> b.snapshot_digest
      OR a.approval_schema_version <> :supported_approval_schema
      OR b.binding_schema_version <> :supported_binding_schema
      OR c.snapshot_schema_version <> :supported_snapshot_schema
      OR c.retention_mode <> 'retain'
    )
)
```

Use the correct candidate/target alias in each query. The selection predicate is not sufficient by itself: the same predicate must stay inside the state-mutating `UPDATE`.

### 6.3 PostgreSQL placement

Add the same logical eligibility predicate to:

1. `active_jobs` or the candidate CTE of `_CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL` before `FOR UPDATE ... SKIP LOCKED` (`postgres_scheduler.py:249-330`); and
2. the final `UPDATE work_units ... WHERE` before `RETURNING` (`postgres_scheduler.py:331-369`).

Do not place it only in a subsequent job-status update at `postgres_scheduler.py:576-614`: by then work-unit state already mutated. Reuse bound parameters for supported schema versions, not string interpolation.

### 6.4 Denied-result semantics

`claim_next_scheduled_work_unit()` returns `None` when no eligible work exists, including a binding-inconsistent strict row. For this exact denied row, prove:

- no `work_units` status/worker/token/lease/attempt/timestamp mutation;
- no `translation_jobs` status/timestamp mutation;
- no `scheduler_events` row;
- no `work_unit_attempts` row;
- no provider-slot lease operation;
- worker/scheduler loader does not read the unit object or invoke glossary/provider code.

The current API cannot distinguish an empty queue from Guard-B denial without an observable side effect. Keep this ambiguity in the narrow claim return. If an admin diagnostic is required later, design a separate read-only inspection query; do not log denial during claim.

## 7. Migration, compatibility, and rollback

### 7.1 Forward sequence

1. Owner approves the high-risk schema/runtime implementation packet after architecture synthesis.
2. Deploy code that can read both legacy jobs and the new tables, but keep strict admission disabled until schema capability is verified on every active backend/process.
3. Apply additive tables/indexes. SQLite compatibility must be explicitly tested against existing DB files; PostgreSQL schema initialization alone is not a migration audit trail.
4. Verify strict schema capability by read-only preflight in the store before enabling strict admission.
5. Enable only new DOCX strict admission. Do not backfill existing jobs.

### 7.2 Unknown schema behavior

If the configured backend lacks any strict table/column/index/version expected by the strict path, `admit_strict_docx_job()` must return `strict_schema_unavailable` before job/work-unit insertion. It must not fall back to legacy `create_job()`.

For a strict job encountered by code whose supported binding/schema version is unknown, Guard B makes it non-claimable with no claim-side writes. This protects against dispatch but can leave a queued job; only a separately approved repair/rollback procedure may resolve it.

### 7.3 Legacy and rollback behavior

- Legacy jobs have no binding row and retain their existing claim behavior.
- New strict job binding rows are immutable; do not update approval/digest to "fix" a mismatch.
- Rollback must be **forward-fix only** for any admitted strict job: retain new tables and data; re-deploy a compatible reader or a reviewed repair path. Dropping strict tables, deleting rows, or unilaterally reclassifying strict jobs are destructive data/state changes and require separate owner approval.
- No source-byte immutability is claimed. `snapshot_digest` identifies the approved snapshot representation, not a conditionally versioned source object.

## 8. Verification plan for the later implementation

### SQLite unit/transaction tests

1. Admission succeeds only for approved DOCX request and atomically creates exactly one job, binding, and ordered work units.
2. Each Guard-A refusal (`not docx`, missing approval, status mismatch, digest/custody mismatch, unsupported strict schema) leaves all five job/scheduler tables unchanged; assert zero jobs, units, attempts, events, and leases.
3. Inject exceptions after each admission step (after approval read, job insert, binding insert, first/middle unit insert); assert transaction rollback leaves no partial job/binding/units.
4. Use two independent SQLite store connections against one temporary file and concurrent admission/claim attempts. Prove no duplicate binding, partial strict job, or improper claim. Set a bounded busy timeout/test retry explicitly; document the SQLite locking behavior actually observed.
5. For an intentionally corrupted strict binding, snapshot before/after rows in jobs, units, attempts, events, and leases; call claim; assert `None` and byte-for-byte-equivalent metadata rows except unrelated test setup.
6. Verify denied strict work is not fetched by `worker.py`/`scheduler_runner.py` with storage/provider/glossary spies.
7. Requeue/retry/lease-recovery/resume paths repeatedly hit Guard B before any re-claim state write.

### PostgreSQL parity tests

1. Add contract tests for `SCHEMA_SQL`, strict admission transaction, and both predicate placements in `_CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL`.
2. If `TEST_POSTGRES_DSN` is available, run integration tests for the same atomic admission, denial, requeue/recovery and concurrent-claim cases. If absent, record PostgreSQL integration result as `Unknown`, not passed.
3. Verify no regression of the existing advisory-lock / `SKIP LOCKED` behavior and cancellation protection.

### Redaction/custody tests

1. Assert raw glossary entry text/serialized snapshot never appears in `translation_jobs.translation_policy`, `scheduler_events.payload_json`, `work_unit_attempts.error_message`, logs produced by this path, or exception strings.
2. Assert custody table stores only opaque ref/digest/version/retention metadata.
3. Assert runtime reader receives the opaque ref after successful claim and verifies digest/schema before rendering context.
4. Assert no TTL/delete/cleanup operation is added or called.

### Commands (after implementation only)

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs tests.test_persistent_planner tests.test_scheduler tests.test_scheduler_runner
PYTHONPATH=src python3 -m unittest tests.test_postgres_scheduler
PYTHONPATH=src python3 -m compileall src
```

No provider calls are part of this spike or its core store tests.

## 9. Stop conditions / Unknowns

- **TBD owner approval:** database migration/state plus scheduler/runtime behavior implementation is high risk; the policy approval recorded for this spike is not implementation approval.
- **Unknown:** whether the operational PostgreSQL deployment exists and which migration executor/process sequencing is used; repository code only shows runtime `SCHEMA_SQL` initialization.
- **Unknown:** whether the current local object storage can provide opaque snapshot custody with durable read semantics without a new storage design. Do not assume object-store conditional versioning or source-byte immutability.
- **TBD owner decision before a later retention slice:** retention/deletion lifecycle, cleanup actor, and restore/backup treatment of custody objects.
- **TBD architecture decision if required by implementation:** whether strict admission may write intermediate work-unit source objects before the database transaction and what compensating cleanup, if any, is allowed. This spike does not authorize cleanup.
- Stop and return to owner decision if implementation requires changing auth/RBAC, provider configuration/spend, Telegram/server operations, public/raw publication, production dependency, or TXT/EPUB/legacy behavior.

