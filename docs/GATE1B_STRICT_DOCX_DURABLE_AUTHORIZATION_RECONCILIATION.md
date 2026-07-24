# Gate 1B strict DOCX durable authorization: current-main reconciliation

**Date:** 2026-07-24
**Baseline verified:** `HEAD` is `19dc0455e4c9a05af564c0191fac977b40bf11df` (`test(gate1b): verify durable binding boundaries (#837)`).
**Task type:** spike/discovery and docs-only.
**Risk level:** high for any follow-on: persistent database state, scheduler claim semantics, worker/provider admission, and backend parity.
**Approval status:** this reconciliation changes no production code, state, provider configuration, PR, or merge. The approved bounded implementation route is recorded in `docs/GATE1B_POSTGRES_TARGET_CONTRACT.md`. The earlier readiness spike remains a design packet and was not, by itself, approval to change database/state or runtime behavior (`docs/GATE1B_STRICT_DOCX_DURABLE_AUTHORIZATION_SPIKE.md:21,27,301`). The approved route does not prove or independently approve PostgreSQL implementation, a migration, runtime activation, rollout, Gate 1 closure, beta, release, or quality outcome.

## Scope and non-goals

**In scope:** source-pinning the present strict DOCX approval, custody, binding, admission, claim, revocation, and legacy-path seams.

**Out of scope:** code/schema changes; TXT/EPUB; legacy behavior migration; provider calls; Telegram/server/deploy work; cache/auth/RBAC changes; retention/cleanup; a PR or merge; any quality, rollout, Gate 1, beta, or release claim.

## Confirmed facts

### 1. SQLite approval, custody, and binding exist now

- `GlossaryApproval` stores `approval_id`, `custody_id`, digest, snapshot/approval schema versions, status, and revocation time in `src/translator_service/persistent_jobs.py:90-100`.
- SQLite `create_glossary_approval()` verifies the payload SHA-256 and supported schema versions, then begins `BEGIN IMMEDIATE`, creates/reuses a custody row, and inserts an `approved` approval row atomically (`persistent_jobs.py:243-311`).
- Current custody is SQLite-local `snapshot_payload BLOB`, not the opaque external `snapshot_ref` proposed by the readiness spike (`persistent_jobs.py:1892-1900`). Its only supported retention value is `retain`.
- `revoke_glossary_approval()` sets `approval_status='revoked'` and `revoked_at` within `BEGIN IMMEDIATE` (`persistent_jobs.py:313-332`).
- The SQLite schema creates `glossary_approvals` and immutable-per-job `strict_job_glossary_bindings` tables. The binding records `approval_id`, `custody_id`, digest, and binding schema version; `job_id` is its primary key (`persistent_jobs.py:1905-1932`).
- `delete_job()` declines deletion when a strict binding exists (`persistent_jobs.py:613-643`). No retention/cleanup API was found in the opened strict seam.

### 2. Strict admission is implemented for SQLite only

- `StrictDocxAdmissionRequest` contains an approval id, document/job metadata, ordered work-unit plans, and strict/approval/binding/snapshot schema values (`persistent_jobs.py:109-128`). It does **not** accept a caller-supplied custody id or expected snapshot digest; the store derives binding values from the selected approval row.
- `SQLiteTranslationJobStore.admit_strict_docx_job()` begins `BEGIN IMMEDIATE`, validates the request, reads approval plus custody, fails before writes for invalid/missing/revoked/mismatched approval, rejects an approval already bound to any strict job, then inserts job, binding, and all work units before one commit (`persistent_jobs.py:363-484`).
- The request validator requires `document_kind == 'docx'`, exact supported versions, non-empty contiguous sequences starting at one, non-empty block/hash values, and every unit's source key matching the request key (`persistent_jobs.py:2185-2234`).
- Exact admission binding values are the approval row's `custody_id` and `snapshot_digest`; the binding schema is `request.binding_schema_version` (`persistent_jobs.py:433-447`). Approval and custody schema values are validated against request versions (`persistent_jobs.py:2266-2282`).
- `create_persistent_strict_docx_job_plan()` checks the storage metadata filename extension, reads and plans the DOCX, creates work-unit hashes tied to the supplied source-object key, and calls the SQLite admission API once (`persistent_planner.py:63-144`). It reads source bytes before admission. This is not a source-byte immutability/versioning guarantee.

### 3. SQLite revalidates at claim time and fails closed before worker/provider work

- `_strict_docx_claim_guard()` rejects a present binding when approval/custody is missing, revoked/not approved, custody/digest/schema inconsistent, or retention is not `retain` (`persistent_jobs.py:2237-2263`). Absence of a binding remains eligible and therefore preserves legacy behavior.
- The direct `claim_next_work_unit()` applies this guard to both candidate selection and state-mutating update (`persistent_jobs.py:748-813`).
- The scheduled SQLite claim applies it both to candidate selection and the conditional work-unit `UPDATE` (`persistent_jobs.py:884-1105`). Only after a successful update does it mark the job translating and record `work_unit_claimed` (`persistent_jobs.py:1101-1134`).
- The worker and scheduler runner invoke `claim_next_scheduled_work_unit()` before loading the source object, leasing provider capacity, resolving glossary hooks, or provider translation (`worker.py:725-816`; `scheduler_runner.py:249-357`). For a rejected strict row, the store returns `None`; these paths do none of those later operations.
- Because the claim guard checks `approval_status` every candidate/update, a revoked approval is non-claimable on the next direct or scheduled SQLite claim. The scheduled statuses include pending, failed, and failed-retryable (`persistent_jobs.py:910-941`, `1018-1097`), so retryable/requeue candidates pass through Guard B again.

### 4. Regular DOCX and `with_glossary` paths bypass strict admission

- The production-facing dispatcher always calls the ordinary `create_persistent_docx_job_plan()` for DOCX (`bot_translation_service.py:4435-4466`). It has no approval id and never calls `create_persistent_strict_docx_job_plan()`.
- The ordinary DOCX planner performs the legacy split `create_job()` then `add_work_units()` and places `glossary_mode`/prepared-package metadata in generic `translation_policy` (`persistent_planner.py:225-298`, `398-447`).
- Existing worker glossary behavior reads the generic policy's `glossary_mode`; repository search locates `with_glossary` creation/use in the generic package/worker path, not a strict binding route (`worker.py:935-955,2041-2051`; `glossary_prepared_provider.py:167,182,312`).
- Therefore ordinary DOCX and existing `with_glossary` jobs can bypass the strict SQLite API. This is currently legacy behavior, not proof that strict authorization is enabled for them.

### 5. PostgreSQL and interface parity are absent

- `PersistentJobStore` remains the common API. The four SQLite strict-DOCX APIs—glossary-approval creation/revocation, custody read, and strict admission—are declared on `SQLiteStrictDocxJobStore` (`persistent_job_store.py:21-96`). `PostgresSchedulerStore` does not implement that strict capability, so backend parity remains absent.
- `PostgresSchedulerStore` and `SCHEMA_SQL` contain only ordinary job/work-unit/scheduler/provider-slot structures in the opened source; no Gate 1B custody, approval, or strict-binding tables, methods, or claim predicate were found (`postgres_scheduler.py:61-196,219-369,431-623`).
- PostgreSQL's claim CTE and final update contain no strict binding eligibility check (`postgres_scheduler.py:249-369`).
- `read_approved_glossary_snapshot()` returns payload only when SQLite approval/custody consistency is valid (`persistent_jobs.py:334-361`), but no opened worker/scheduler call consumes it. A strict SQLite job is therefore admission/claim guarded, but the current runtime glossary hook is not demonstrably sourced from its durable approval/custody record.

## Unknowns and evidence limits

- **Unknown:** whether any operational PostgreSQL backend exists, its migration executor, and its actual deployed schema. The repository only proves runtime initialization through `SCHEMA_SQL`.
- **Unknown:** whether the intended product contract accepts SQLite-local payload custody or requires the spike's opaque durable custody reference.
- **Unknown:** whether a strict job needs exactly one approval per job. Current SQLite denies reusing an approval (`approval_already_bound`); the readiness spike's proposed schema did not require that uniqueness.
- **Unknown:** comprehensive failure-injection, concurrent-connection, no-side-effect-denial, requeue/recovery, runtime-custody, and PostgreSQL parity coverage. The focused modules currently pass, but their 61 tests are not evidence for these unobserved cases.
- **Not claimed:** source-byte immutability, object-store conditional versioning, durable runtime glossary activation, provider safety, translation quality, Gate 1 closure, beta/release readiness, or production deployment state.

## Supersession and approved target route

This reconciliation is the source-pinned baseline merged through #837. Its former Planning Council options are superseded by the approved bounded route in `docs/GATE1B_POSTGRES_TARGET_CONTRACT.md`:

- PostgreSQL is the target durable/runtime backend; SQLite is local/test/reference implementation.
- The new strict DOCX path must use one backend-neutral capability and typed pre-write denial when a selected backend lacks that capability. It must never fall back to legacy `create_job()`.
- Ordinary DOCX, existing `with_glossary`, TXT, EPUB, Telegram dispatch, cache policy, deployment and generic migration remain out of scope.
- A strict binding reader must revalidate approval/custody/snapshot before any runtime glossary context is called approved. This baseline does not prove that reader or runtime activation exists.
- The target permits one approval to bind multiple strict jobs only when custody and snapshot digest exactly match; every job binding remains immutable. The present SQLite one-approval-per-job behavior in the confirmed facts above is not target parity evidence.
- The later unversioned PostgreSQL strict-DOCX working-tree variant is superseded before merge. Slice M0 pins `19dc045` as migration v1, assigns exactly the three strict DDL table definitions to migration v2, and separates them from later strict behavior/review hunks. See `docs/GATE1B_POSTGRES_MIGRATION_RECONCILIATION.md`.

The approved route is not PostgreSQL implementation, migration execution, runtime activation, quality evidence, Gate 1 closure, beta/release readiness, or deployment evidence. Follow-on implementation must use targeted contract tests and report PostgreSQL integration as `Unknown` unless the existing `TEST_POSTGRES_DSN` integration path actually runs.
