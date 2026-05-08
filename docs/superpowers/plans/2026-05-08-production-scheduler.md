# Production Scheduler Implementation Plan


**Goal:** Build a PostgreSQL-first translation scheduler contract with leases, claim tokens, retries, cancellation, resume, assembly orchestration, and a production repository path while preserving the existing local persistent-job flow.

**Architecture:** Introduce a scheduler contract module first, then adapt the current SQLite job store to that contract so existing planner, worker, bot, and assembly code keep working while the state machine becomes production-shaped. After the contract is protected by tests, add a psycopg-backed PostgreSQL repository with real claim SQL using `FOR UPDATE SKIP LOCKED`, and wire the worker CLI to the scheduler loop without requiring Redis for correctness.

**Tech Stack:** Python 3.13, dataclasses, `StrEnum`, `sqlite3`, `psycopg`, PostgreSQL 16, existing `unittest` suite, existing local object storage and format adapters.

---

## Scope

This plan implements the scheduler foundation from `docs/superpowers/specs/2026-05-08-production-scheduler-design.md`.

Included:

- Scheduler domain contracts and repository protocol.
- SQLite adapter evolution for local/dev parity.
- Claim tokens, leases, expired-lease recovery, retryable/terminal failures.
- Attempt audit rows and scheduler event rows in the local store.
- Worker orchestration loop that claims, translates, completes, retries, and assembles.
- PostgreSQL schema and repository implementation.
- Worker CLI configuration for SQLite or PostgreSQL scheduler backends.

Excluded:

- Redis notification/wakeup layer.
- Payment-provider integration.
- Admin dashboard.
- Automatic incompatible replan/migration.

## File Structure

- Create `src/translator_service/scheduler.py` for scheduler enums, dataclasses, retry policy helpers, limit settings, and the repository protocol.
- Modify `src/translator_service/persistent_jobs.py` so `SQLiteTranslationJobStore` implements the scheduler contract while preserving current public methods used by planners and tests.
- Modify `src/translator_service/worker.py` so stored work-unit execution uses `SchedulerClaim` and completes/fails through claim tokens.
- Create `src/translator_service/scheduler_runner.py` for the long-running claim/execute/assemble loop shared by CLI workers and future service runners.
- Create `src/translator_service/postgres_scheduler.py` for PostgreSQL schema creation and psycopg repository implementation.
- Modify `src/translator_service/config.py` for scheduler backend, PostgreSQL DSN, lease, retry, and polling settings.
- Modify `src/translator_service/bot/runtime.py` only to pass scheduler-related settings into service construction when needed.
- Modify `src/translator_service/bot_translation_service.py` only where current direct `until_idle` calls need to call the scheduler runner.
- Modify `tests/test_persistent_jobs.py`, `tests/test_worker.py`, `tests/test_bot_translation_service.py`, and create `tests/test_scheduler.py`, `tests/test_scheduler_runner.py`, `tests/test_postgres_scheduler.py`.

## Task 1: Scheduler Contract

**Files:**

- Create: `src/translator_service/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write scheduler contract tests**

Add `tests/test_scheduler.py`:

```python
from datetime import UTC, datetime, timedelta
import unittest

from translator_service.scheduler import (
    RetryDecision,
    SchedulerClaim,
    SchedulerJobStatus,
    SchedulerLimits,
    SchedulerWorkUnitStatus,
    WorkUnitFailureKind,
    calculate_retry_decision,
)


class SchedulerContractTest(unittest.TestCase):
    def test_status_values_are_persisted_contract_values(self):
        self.assertEqual(SchedulerJobStatus.QUEUED.value, "queued")
        self.assertEqual(SchedulerJobStatus.CANCEL_REQUESTED.value, "cancel_requested")
        self.assertEqual(SchedulerJobStatus.ASSEMBLING.value, "assembling")
        self.assertEqual(SchedulerJobStatus.PARTIAL.value, "partial")
        self.assertEqual(SchedulerWorkUnitStatus.FAILED_RETRYABLE.value, "failed_retryable")
        self.assertEqual(SchedulerWorkUnitStatus.FAILED_TERMINAL.value, "failed_terminal")

    def test_retry_decision_uses_exponential_backoff_with_cap(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)

        decision = calculate_retry_decision(
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            attempt_count=2,
            max_attempts=5,
            now=now,
            base_delay_seconds=10,
            max_delay_seconds=120,
        )

        self.assertEqual(
            decision,
            RetryDecision(
                retryable=True,
                next_status=SchedulerWorkUnitStatus.FAILED_RETRYABLE,
                available_at=now + timedelta(seconds=20),
                terminal_job_status=None,
            ),
        )

    def test_retry_decision_interrupts_after_max_attempts(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)

        decision = calculate_retry_decision(
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            attempt_count=5,
            max_attempts=5,
            now=now,
            base_delay_seconds=10,
            max_delay_seconds=120,
        )

        self.assertEqual(decision.retryable, False)
        self.assertEqual(decision.next_status, SchedulerWorkUnitStatus.FAILED_TERMINAL)
        self.assertEqual(decision.terminal_job_status, SchedulerJobStatus.INTERRUPTED)

    def test_scheduler_claim_carries_token_and_lease(self):
        lease_until = datetime(2026, 5, 8, 12, 5, tzinfo=UTC)

        claim = SchedulerClaim(
            job_id="job-1",
            work_unit_id="job-1:unit-1",
            worker_id="worker-a",
            claim_token="claim-token-1",
            lease_until=lease_until,
            attempt_number=1,
            source_object_key="intermediate/job-1/unit-1.txt",
        )

        self.assertEqual(claim.claim_token, "claim-token-1")
        self.assertEqual(claim.lease_until, lease_until)

    def test_scheduler_limits_have_safe_defaults(self):
        limits = SchedulerLimits()

        self.assertEqual(limits.max_active_units_per_job, 1)
        self.assertEqual(limits.max_active_jobs_per_user, 1)
        self.assertEqual(limits.max_active_units_global, 8)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the contract tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_scheduler.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'translator_service.scheduler'`.

- [ ] **Step 3: Implement the scheduler contract**

Create `src/translator_service/scheduler.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol


class SchedulerJobStatus(StrEnum):
    QUEUED = "queued"
    TRANSLATING = "translating"
    ASSEMBLING = "assembling"
    PARTIAL = "partial"
    READY = "ready"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    EXPIRED = "expired"


class SchedulerWorkUnitStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    CACHED = "cached"


class WorkUnitFailureKind(StrEnum):
    RETRYABLE_PROVIDER = "retryable_provider"
    MALFORMED_PROVIDER_OUTPUT = "malformed_provider_output"
    LEASE_EXPIRED = "lease_expired"
    MISSING_SOURCE_OBJECT = "missing_source_object"
    UNSUPPORTED_CONTRACT = "unsupported_contract"
    ASSEMBLY_MAPPING_FAILED = "assembly_mapping_failed"


@dataclass(frozen=True)
class SchedulerLimits:
    max_active_units_per_job: int = 1
    max_active_jobs_per_user: int = 1
    max_active_units_per_user: int = 2
    max_active_units_global: int = 8
    max_attempts_per_unit: int = 3


@dataclass(frozen=True)
class SchedulerClaim:
    job_id: str
    work_unit_id: str
    worker_id: str
    claim_token: str
    lease_until: datetime
    attempt_number: int
    source_object_key: str | None


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    next_status: SchedulerWorkUnitStatus
    available_at: datetime
    terminal_job_status: SchedulerJobStatus | None


def utc_now() -> datetime:
    return datetime.now(UTC)


def calculate_retry_decision(
    *,
    failure_kind: WorkUnitFailureKind,
    attempt_count: int,
    max_attempts: int,
    now: datetime,
    base_delay_seconds: int,
    max_delay_seconds: int,
) -> RetryDecision:
    terminal_failures = {
        WorkUnitFailureKind.MISSING_SOURCE_OBJECT,
        WorkUnitFailureKind.UNSUPPORTED_CONTRACT,
        WorkUnitFailureKind.ASSEMBLY_MAPPING_FAILED,
    }
    if failure_kind in terminal_failures or attempt_count >= max_attempts:
        return RetryDecision(
            retryable=False,
            next_status=SchedulerWorkUnitStatus.FAILED_TERMINAL,
            available_at=now,
            terminal_job_status=SchedulerJobStatus.INTERRUPTED,
        )

    delay = min(base_delay_seconds * (2 ** max(0, attempt_count - 1)), max_delay_seconds)
    return RetryDecision(
        retryable=True,
        next_status=SchedulerWorkUnitStatus.FAILED_RETRYABLE,
        available_at=now + timedelta(seconds=delay),
        terminal_job_status=None,
    )


class SchedulerRepository(Protocol):
    def claim_next_work_unit(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        limits: SchedulerLimits,
    ) -> SchedulerClaim | None:
        pass

    def complete_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> None:
        pass

    def fail_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        failure_kind: WorkUnitFailureKind,
        error_message: str,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
    ) -> None:
        pass
```

- [ ] **Step 4: Run the contract tests to verify they pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_scheduler.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/translator_service/scheduler.py tests/test_scheduler.py
git commit -m "Add scheduler domain contract"
```

## Task 2: SQLite Claim Tokens And Leases

**Files:**

- Modify: `src/translator_service/persistent_jobs.py`
- Modify: `tests/test_persistent_jobs.py`

- [ ] **Step 1: Write failing SQLite scheduler tests**

Append these tests to `SQLiteTranslationJobStoreTest` in `tests/test_persistent_jobs.py`:

```python
    def test_scheduler_claim_sets_token_lease_and_attempt_count(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)

        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_global=4),
        )
        claimed_unit = store.list_work_units(job.id)[0]

        self.assertEqual(claim.job_id, job.id)
        self.assertEqual(claim.work_unit_id, claimed_unit.id)
        self.assertEqual(claim.worker_id, "worker-a")
        self.assertTrue(claim.claim_token)
        self.assertEqual(claim.attempt_number, 1)
        self.assertEqual(claimed_unit.worker_id, "worker-a")
        self.assertEqual(claimed_unit.claim_token, claim.claim_token)
        self.assertIsNotNone(claimed_unit.lease_until)
        self.assertEqual(claimed_unit.attempt_count, 1)

    def test_completion_requires_matching_claim_token(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        with self.assertRaises(ValueError):
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token="stale-token",
                translated_text="stale completion",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

        store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text="valid completion",
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
        )

        first_unit = store.list_work_units(job.id)[0]
        self.assertEqual(first_unit.translated_text, "valid completion")
```

- [ ] **Step 2: Run the SQLite tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_persistent_jobs.py
```

Expected: FAIL because `claim_next_scheduled_work_unit`, `claim_token`, `lease_until`, and `attempt_count` do not exist.

- [ ] **Step 3: Extend persistent work-unit dataclass and schema**

In `src/translator_service/persistent_jobs.py`, add imports:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from translator_service.scheduler import SchedulerClaim, SchedulerLimits
```

Extend `PersistentTranslationJobStatus` with production scheduler states while
keeping existing values:

```python
    ASSEMBLING = "assembling"
    PARTIAL = "partial"
    CANCEL_REQUESTED = "cancel_requested"
    EXPIRED = "expired"
```

Add `priority: int` to `PersistentTranslationJob` with a default database value
of `0`, because scheduled claims order by job priority:

```python
    priority: int
```

In `CREATE TABLE IF NOT EXISTS translation_jobs`, add:

```sql
                    priority INTEGER NOT NULL DEFAULT 0,
```

After table creation, add a column migration:

```python
            _ensure_column(
                self._connection,
                table_name="translation_jobs",
                column_name="priority",
                definition="priority INTEGER NOT NULL DEFAULT 0",
            )
```

Update `_job_from_row`:

```python
        priority=row["priority"],
```

Extend `PersistentWorkUnit`:

```python
    claim_token: str | None
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_until: datetime | None
```

In `CREATE TABLE IF NOT EXISTS work_units`, add columns:

```sql
                    claim_token TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    available_at TEXT,
                    lease_until TEXT,
```

After table creation, add column migrations:

```python
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="claim_token",
                definition="claim_token TEXT",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="attempt_count",
                definition="attempt_count INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="max_attempts",
                definition="max_attempts INTEGER NOT NULL DEFAULT 3",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="available_at",
                definition="available_at TEXT",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="lease_until",
                definition="lease_until TEXT",
            )
```

Update `_work_unit_from_row`:

```python
        claim_token=row["claim_token"],
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        available_at=(
            _from_db_time(row["available_at"])
            if row["available_at"]
            else _from_db_time(row["created_at"])
        ),
        lease_until=(
            _from_db_time(row["lease_until"]) if row["lease_until"] else None
        ),
```

- [ ] **Step 4: Implement scheduled claim and tokened completion**

Add methods to `SQLiteTranslationJobStore`:

```python
    def claim_next_scheduled_work_unit(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        limits: SchedulerLimits,
    ) -> SchedulerClaim | None:
        now = _now()
        active_global = self._connection.execute(
            """
            SELECT COUNT(*) AS count FROM work_units
            WHERE status = ?
            """,
            (PersistentWorkUnitStatus.TRANSLATING.value,),
        ).fetchone()
        if active_global["count"] >= limits.max_active_units_global:
            return None

        row = self._connection.execute(
            """
            SELECT wu.*
            FROM work_units wu
            JOIN translation_jobs tj ON tj.id = wu.job_id
            WHERE tj.status IN (?, ?)
              AND wu.status IN (?, ?)
              AND (wu.available_at IS NULL OR datetime(wu.available_at) <= datetime(?))
              AND (wu.lease_until IS NULL OR datetime(wu.lease_until) <= datetime(?))
            ORDER BY tj.priority DESC, datetime(tj.created_at), wu.sequence
            LIMIT 1
            """,
            (
                PersistentTranslationJobStatus.QUEUED.value,
                PersistentTranslationJobStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.PENDING.value,
                PersistentWorkUnitStatus.FAILED.value,
                _to_db_time(now),
                _to_db_time(now),
            ),
        ).fetchone()
        if row is None:
            return None

        claim_token = uuid4().hex
        lease_until = now + timedelta(seconds=max(1, lease_seconds))
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = ?, claim_token = ?,
                    lease_until = ?, attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    worker_id,
                    claim_token,
                    _to_db_time(lease_until),
                    _to_db_time(now),
                    _to_db_time(now),
                    row["id"],
                ),
            )
            self._update_job_status(
                row["job_id"],
                PersistentTranslationJobStatus.TRANSLATING,
                now=now,
            )
        claimed = self._require_work_unit(row["id"])
        return SchedulerClaim(
            job_id=claimed.job_id,
            work_unit_id=claimed.id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_until=lease_until,
            attempt_number=claimed.attempt_count,
            source_object_key=claimed.source_object_key,
        )

    def complete_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> PersistentWorkUnit:
        work_unit = self._require_work_unit(work_unit_id)
        if work_unit.claim_token != claim_token:
            raise ValueError(f"Stale work-unit claim: {work_unit_id}")
        completed = self.complete_work_unit(
            work_unit_id,
            translated_text=translated_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=cache_hit_tokens,
            cache_miss_tokens=cache_miss_tokens,
        )
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET claim_token = NULL, lease_until = NULL, worker_id = NULL
                WHERE id = ?
                """,
                (work_unit_id,),
            )
            job = self._require_job(completed.job_id)
            if (
                job.status is PersistentTranslationJobStatus.READY
                and job.final_object_key is None
            ):
                self._update_job_status(
                    completed.job_id,
                    PersistentTranslationJobStatus.ASSEMBLING,
                    now=_now(),
                )
        return self._require_work_unit(work_unit_id)
```

Update the existing `complete_work_unit` method to clear `claim_token`, `lease_until`, and `worker_id` in its `UPDATE`.

- [ ] **Step 5: Run persistent job tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_persistent_jobs.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/translator_service/persistent_jobs.py tests/test_persistent_jobs.py
git commit -m "Add scheduler claims to SQLite job store"
```

## Task 3: Retryable Failures, Attempts, Events, Heartbeats, And Expired Leases

**Files:**

- Modify: `src/translator_service/persistent_jobs.py`
- Modify: `tests/test_persistent_jobs.py`

- [ ] **Step 1: Write failing retry and lease tests**

Append to `SQLiteTranslationJobStoreTest`:

```python
    def test_retryable_failure_records_attempt_and_delays_reclaim(self):
        from translator_service.scheduler import (
            SchedulerLimits,
            WorkUnitFailureKind,
        )

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=600,
        )
        immediate = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        attempts = store.list_work_unit_attempts(claim.work_unit_id)

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_RETRYABLE)
        self.assertIsNone(immediate)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].error_message, "provider timeout")

    def test_expired_lease_is_recovered_for_retry(self):
        from datetime import timedelta
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=1,
            limits=SchedulerLimits(),
        )

        recovered = store.recover_expired_leases(
            now=claim.lease_until + timedelta(seconds=1),
            retry_base_delay_seconds=0,
            retry_max_delay_seconds=0,
        )
        reclaimed = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(reclaimed.work_unit_id, claim.work_unit_id)
        self.assertNotEqual(reclaimed.claim_token, claim.claim_token)

    def test_scheduler_events_capture_claim_complete_and_retry(self):
        from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=600,
        )

        events = store.list_scheduler_events(job.id)

        self.assertEqual(
            [event.event_type for event in events],
            ["work_unit_claimed", "work_unit_retry_scheduled"],
        )
        self.assertEqual(events[0].job_id, job.id)
        self.assertEqual(events[0].work_unit_id, claim.work_unit_id)

    def test_worker_heartbeat_is_upserted(self):
        store = self._memory_store()

        store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="idle",
            active_job_id=None,
            active_work_unit_id=None,
        )
        store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="busy",
            active_job_id="job-1",
            active_work_unit_id="job-1:unit-1",
        )

        heartbeat = store.get_worker_heartbeat("worker-a")

        self.assertEqual(heartbeat.worker_id, "worker-a")
        self.assertEqual(heartbeat.status, "busy")
        self.assertEqual(heartbeat.active_job_id, "job-1")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_persistent_jobs.py
```

Expected: FAIL because retryable status, attempts/events/heartbeat tables, and expired lease recovery do not exist.

- [ ] **Step 3: Add retryable status aliases**

Update `PersistentWorkUnitStatus` in `src/translator_service/persistent_jobs.py`:

```python
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
```

Keep `FAILED = "failed"` for old rows and existing tests. Treat old `failed` rows as retryable in claim/resume code.

- [ ] **Step 4: Add attempt dataclass and schema**

Add dataclass:

```python
@dataclass(frozen=True)
class PersistentWorkUnitAttempt:
    id: str
    work_unit_id: str
    job_id: str
    attempt_number: int
    worker_id: str | None
    claim_token: str | None
    status: str
    error_code: str | None
    error_message: str | None
    retry_after_seconds: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class PersistentSchedulerEvent:
    id: str
    job_id: str
    work_unit_id: str | None
    event_type: str
    payload_json: str
    created_at: datetime


@dataclass(frozen=True)
class PersistentWorkerHeartbeat:
    worker_id: str
    worker_kind: str
    status: str
    active_job_id: str | None
    active_work_unit_id: str | None
    started_at: datetime
    last_seen_at: datetime
```

Add schema:

```sql
CREATE TABLE IF NOT EXISTS work_unit_attempts (
                    id TEXT PRIMARY KEY,
                    work_unit_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    worker_id TEXT,
                    claim_token TEXT,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    retry_after_seconds INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    FOREIGN KEY(work_unit_id) REFERENCES work_units(id),
                    FOREIGN KEY(job_id) REFERENCES translation_jobs(id)
                )
```

Add scheduler events schema:

```sql
                CREATE TABLE IF NOT EXISTS scheduler_events (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    work_unit_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES translation_jobs(id)
                )
```

Add worker heartbeat schema:

```sql
                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    worker_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_job_id TEXT,
                    active_work_unit_id TEXT,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
```

- [ ] **Step 5: Implement `fail_claimed_work_unit`, attempts listing, and lease recovery**

Add methods:

```python
    def fail_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        failure_kind,
        error_message: str,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
    ) -> PersistentWorkUnit:
        from translator_service.scheduler import calculate_retry_decision

        work_unit = self._require_work_unit(work_unit_id)
        if work_unit.claim_token != claim_token:
            raise ValueError(f"Stale work-unit claim: {work_unit_id}")
        now = _now()
        decision = calculate_retry_decision(
            failure_kind=failure_kind,
            attempt_count=work_unit.attempt_count,
            max_attempts=work_unit.max_attempts,
            now=now,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        )
        retry_after = max(0, int((decision.available_at - now).total_seconds()))
        with self._connection:
            self._insert_attempt(
                work_unit=work_unit,
                status=decision.next_status.value,
                error_code=failure_kind.value,
                error_message=error_message,
                retry_after_seconds=retry_after,
                finished_at=now,
            )
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, last_error = ?, worker_id = NULL,
                    claim_token = NULL, lease_until = NULL, available_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    decision.next_status.value,
                    error_message,
                    _to_db_time(decision.available_at),
                    _to_db_time(now),
                    work_unit_id,
                ),
            )
            if decision.terminal_job_status is not None:
                self._update_job_status(
                    work_unit.job_id,
                    PersistentTranslationJobStatus.INTERRUPTED,
                    now=now,
                )
        return self._require_work_unit(work_unit_id)

    def recover_expired_leases(
        self,
        *,
        now: datetime,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
    ) -> int:
        expired = self._connection.execute(
            """
            SELECT id FROM work_units
            WHERE status = ? AND lease_until IS NOT NULL
              AND datetime(lease_until) <= datetime(?)
            ORDER BY datetime(lease_until)
            """,
            (PersistentWorkUnitStatus.TRANSLATING.value, _to_db_time(now)),
        ).fetchall()
        for row in expired:
            work_unit = self._require_work_unit(row["id"])
            self.fail_claimed_work_unit(
                work_unit_id=work_unit.id,
                claim_token=work_unit.claim_token or "",
                failure_kind=WorkUnitFailureKind.LEASE_EXPIRED,
                error_message="work unit lease expired",
                retry_base_delay_seconds=retry_base_delay_seconds,
                retry_max_delay_seconds=retry_max_delay_seconds,
            )
        return len(expired)
```

Add `_insert_attempt` and `list_work_unit_attempts` using `PersistentWorkUnitAttempt`.

Add event helpers:

```python
    def list_scheduler_events(self, job_id: str) -> list[PersistentSchedulerEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM scheduler_events
            WHERE job_id = ?
            ORDER BY datetime(created_at), id
            """,
            (job_id,),
        ).fetchall()
        return [_scheduler_event_from_row(row) for row in rows]

    def _record_scheduler_event(
        self,
        *,
        job_id: str,
        work_unit_id: str | None,
        event_type: str,
        payload: dict[str, object],
        now: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO scheduler_events (
                id, job_id, work_unit_id, event_type, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"event-{uuid4().hex}",
                job_id,
                work_unit_id,
                event_type,
                json.dumps(payload, sort_keys=True),
                _to_db_time(now),
            ),
        )
```

Call `_record_scheduler_event(..., event_type="work_unit_claimed", ...)` in
`claim_next_scheduled_work_unit`, `"work_unit_completed"` in
`complete_claimed_work_unit`, `"work_unit_retry_scheduled"` for retryable
failure, and `"work_unit_failed_terminal"` for terminal failure.

Add heartbeat methods:

```python
    def record_worker_heartbeat(
        self,
        *,
        worker_id: str,
        worker_kind: str,
        status: str,
        active_job_id: str | None,
        active_work_unit_id: str | None,
    ) -> PersistentWorkerHeartbeat:
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO worker_heartbeats (
                    worker_id, worker_kind, status, active_job_id,
                    active_work_unit_id, started_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    worker_kind = excluded.worker_kind,
                    status = excluded.status,
                    active_job_id = excluded.active_job_id,
                    active_work_unit_id = excluded.active_work_unit_id,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    worker_id,
                    worker_kind,
                    status,
                    active_job_id,
                    active_work_unit_id,
                    _to_db_time(now),
                    _to_db_time(now),
                ),
            )
        return self.get_worker_heartbeat(worker_id)

    def get_worker_heartbeat(self, worker_id: str) -> PersistentWorkerHeartbeat | None:
        row = self._connection.execute(
            "SELECT * FROM worker_heartbeats WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        if row is None:
            return None
        return _worker_heartbeat_from_row(row)
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_persistent_jobs.py tests/test_scheduler.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/translator_service/persistent_jobs.py tests/test_persistent_jobs.py
git commit -m "Add retry leases and attempt audit"
```

## Task 4: Worker Uses Scheduler Claims

**Files:**

- Modify: `src/translator_service/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing worker claim-token test**

Add to `WorkerTest`:

```python
    def test_scheduled_worker_completes_claimed_unit_with_claim_token(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
            )

            self.assertEqual(completed.id, "job-1:unit-1")
            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertIsNone(completed.claim_token)
            self.assertIsNone(completed.lease_until)
            self.assertEqual(completed.translated_text, "[uk] First paragraph")
```

Add import:

```python
    run_next_scheduled_stored_text_work_unit,
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_worker.py
```

Expected: FAIL because `run_next_scheduled_stored_text_work_unit` does not exist.

- [ ] **Step 3: Implement scheduled worker primitive**

In `src/translator_service/worker.py`, add imports:

```python
from translator_service.scheduler import (
    SchedulerLimits,
    WorkUnitFailureKind,
)
```

Add function:

```python
def run_next_scheduled_stored_text_work_unit(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    worker_id: str,
    lease_seconds: int,
    limits: SchedulerLimits,
    translator: PersistentWorkUnitTranslator,
    retry_base_delay_seconds: int = 30,
    retry_max_delay_seconds: int = 600,
    encoding: str = "utf-8",
) -> PersistentWorkUnit | None:
    claim = store.claim_next_scheduled_work_unit(
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        limits=limits,
    )
    if claim is None:
        return None
    work_unit = store.get_work_unit(claim.work_unit_id)
    if work_unit is None:
        raise ValueError(f"Claimed work unit does not exist: {claim.work_unit_id}")

    try:
        translation_result = _translate_stored_text_work_unit(
            storage=storage,
            work_unit=work_unit,
            translator=translator,
            encoding=encoding,
        )
    except FileNotFoundError as error:
        return store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.MISSING_SOURCE_OBJECT,
            error_message=str(error),
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
    except Exception as error:
        logger.exception(
            "Scheduled worker failed: job_id=%s work_unit_id=%s",
            claim.job_id,
            claim.work_unit_id,
        )
        return store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message=str(error),
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )

    return store.complete_claimed_work_unit(
        work_unit_id=claim.work_unit_id,
        claim_token=claim.claim_token,
        translated_text=translation_result.translated_text,
        prompt_tokens=translation_result.usage.prompt_tokens,
        completion_tokens=translation_result.usage.completion_tokens,
        cache_hit_tokens=translation_result.usage.prompt_cache_hit_tokens,
        cache_miss_tokens=translation_result.usage.prompt_cache_miss_tokens,
    )
```

Expose `get_work_unit` as a public wrapper in `SQLiteTranslationJobStore`:

```python
    def get_work_unit(self, work_unit_id: str) -> PersistentWorkUnit | None:
        return self._get_work_unit(work_unit_id)
```

- [ ] **Step 4: Run worker tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_worker.py tests/test_persistent_jobs.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/translator_service/worker.py src/translator_service/persistent_jobs.py tests/test_worker.py
git commit -m "Run workers through scheduler claims"
```

## Task 5: Scheduler Runner And Assembly Stage

**Files:**

- Create: `src/translator_service/scheduler_runner.py`
- Create: `tests/test_scheduler_runner.py`
- Modify: `src/translator_service/worker.py`

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_scheduler_runner.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    SQLiteTranslationJobStore,
)
from translator_service.scheduler import SchedulerLimits
from translator_service.scheduler_runner import run_scheduler_once
from translator_service.worker import ProviderUsage


class SchedulerRunnerTest(unittest.TestCase):
    def test_run_once_translates_due_unit_and_assembles_ready_txt_result(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(),
                lease_seconds=300,
            )

            persisted_job = store.get_job(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "[uk] First paragraph",
            )


class RunnerTranslator:
    def __init__(self) -> None:
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        return f"[{target_language}] {text}"


if __name__ == "__main__":
    unittest.main()
```

Add missing import in the test:

```python
from translator_service.persistent_jobs import WorkUnitPlan
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_scheduler_runner.py
```

Expected: FAIL because `translator_service.scheduler_runner` does not exist.

- [ ] **Step 3: Implement scheduler runner**

Create `src/translator_service/scheduler_runner.py`:

```python
from dataclasses import dataclass

from translator_service.file_storage import LocalObjectStorage
from translator_service.job_runner import DocumentKind
from translator_service.persistent_assembly import (
    assemble_persistent_docx_result,
    assemble_persistent_epub_result,
    count_unassembled_work_units,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    SQLiteTranslationJobStore,
)
from translator_service.scheduler import SchedulerLimits
from translator_service.worker import (
    PersistentWorkUnitTranslator,
    assemble_translated_text_result,
    run_next_scheduled_stored_text_work_unit,
)


@dataclass(frozen=True)
class SchedulerRunOnceSummary:
    completed_units: int
    failed_units: int
    assembled_jobs: int


def run_scheduler_once(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    limits: SchedulerLimits,
    lease_seconds: int,
) -> SchedulerRunOnceSummary:
    completed_units = 0
    failed_units = 0
    completed = run_next_scheduled_stored_text_work_unit(
        store=store,
        storage=storage,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        limits=limits,
        translator=translator,
    )
    if completed is not None:
        if completed.status.value in {"translated", "cached"}:
            completed_units = 1
        elif completed.status.value.startswith("failed"):
            failed_units = 1

    assembled_jobs = assemble_due_jobs(store=store, storage=storage)
    return SchedulerRunOnceSummary(
        completed_units=completed_units,
        failed_units=failed_units,
        assembled_jobs=assembled_jobs,
    )


def assemble_due_jobs(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
) -> int:
    assembled = 0
    for job in store.list_jobs_by_status(PersistentTranslationJobStatus.ASSEMBLING):
        if job.final_object_key is not None:
            continue
        partial = count_unassembled_work_units(store.list_work_units(job.id)) > 0
        result_name = _translated_file_name(
            job.file_name,
            job.target_language,
            job.document_kind,
            partial=partial,
        )
        if job.document_kind == DocumentKind.TXT.value:
            assemble_translated_text_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name=result_name,
                partial=partial,
            )
        elif job.document_kind == DocumentKind.DOCX.value:
            assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name=result_name,
                partial=partial,
            )
        elif job.document_kind == DocumentKind.EPUB.value:
            assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name=result_name,
                partial=partial,
            )
        store.mark_job_assembled(job.id, partial=partial)
        assembled += 1
    return assembled


def _translated_file_name(
    file_name: str,
    target_language: str,
    document_kind: str,
    *,
    partial: bool,
) -> str:
    suffix = f".{target_language}"
    if partial:
        suffix += ".partial"
    if file_name.lower().endswith(f".{document_kind}"):
        return f"{file_name[: -(len(document_kind) + 1)]}{suffix}.{document_kind}"
    return f"{file_name}{suffix}.{document_kind}"
```

Add `list_jobs_by_status` to `SQLiteTranslationJobStore`:

```python
    def list_jobs_by_status(
        self,
        status: PersistentTranslationJobStatus,
        *,
        limit: int = 50,
    ) -> list[PersistentTranslationJob]:
        rows = self._connection.execute(
            """
            SELECT * FROM translation_jobs
            WHERE status = ?
            ORDER BY datetime(updated_at), id
            LIMIT ?
            """,
            (status.value, max(1, limit)),
        ).fetchall()
        return [_job_from_row(row) for row in rows]
```

Add `mark_job_assembled` to `SQLiteTranslationJobStore`:

```python
    def mark_job_assembled(
        self,
        job_id: str,
        *,
        partial: bool,
    ) -> PersistentTranslationJob:
        status = (
            PersistentTranslationJobStatus.PARTIAL
            if partial
            else PersistentTranslationJobStatus.READY
        )
        with self._connection:
            self._update_job_status(job_id, status, now=_now())
        return self._require_job(job_id)
```

- [ ] **Step 4: Run runner tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_scheduler_runner.py tests/test_worker.py tests/test_persistent_jobs.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/translator_service/scheduler_runner.py src/translator_service/persistent_jobs.py tests/test_scheduler_runner.py
git commit -m "Add scheduler runner assembly loop"
```

## Task 6: PostgreSQL Schema And Repository

**Files:**

- Create: `src/translator_service/postgres_scheduler.py`
- Create: `tests/test_postgres_scheduler.py`

- [ ] **Step 1: Write opt-in PostgreSQL tests**

Create `tests/test_postgres_scheduler.py`:

```python
import os
import unittest

from translator_service.postgres_scheduler import (
    PostgresSchedulerStore,
    initialize_postgres_scheduler_schema,
)
from translator_service.scheduler import SchedulerLimits


POSTGRES_DSN = os.getenv("TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "TEST_POSTGRES_DSN is not set")
class PostgresSchedulerStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = PostgresSchedulerStore(POSTGRES_DSN)
        initialize_postgres_scheduler_schema(self.store.connection)
        self.store.clear_for_tests()

    def tearDown(self):
        self.store.close()

    def test_two_workers_do_not_claim_same_unit(self):
        job = self.store.create_job(
            order_id="order-1",
            user_id="telegram:42",
            file_id="file-1",
            file_name="notes.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="intermediate/job-1/unit-1.txt",
        )
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("txt:0",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key="intermediate/job-1/unit-1.txt",
                )
            ],
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
```

Add import:

```python
from translator_service.persistent_jobs import WorkUnitPlan
```

- [ ] **Step 2: Run opt-in test without DSN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_postgres_scheduler.py
```

Expected: OK with one skipped test.

- [ ] **Step 3: Implement PostgreSQL schema initializer and store skeleton**

Create `src/translator_service/postgres_scheduler.py`:

```python
from datetime import timedelta
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from translator_service.persistent_jobs import (
    PersistentTranslationJob,
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    WorkUnitPlan,
    _job_from_mapping,
    _work_unit_from_mapping,
)
from translator_service.scheduler import SchedulerClaim, SchedulerLimits


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS translation_jobs (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    source_object_key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    pricing_snapshot_id TEXT NOT NULL,
    translation_policy TEXT,
    partial_object_key TEXT,
    final_object_key TEXT,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    cancel_requested_at TIMESTAMPTZ,
    resume_blocked_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS work_units (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
    sequence INTEGER NOT NULL,
    source_block_ids_json TEXT NOT NULL,
    source_object_key TEXT,
    source_text_hash TEXT NOT NULL,
    prompt_tier TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    status TEXT NOT NULL,
    translated_text TEXT,
    worker_id TEXT,
    claim_token TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE(job_id, sequence)
);

CREATE TABLE IF NOT EXISTS work_unit_attempts (
    id TEXT PRIMARY KEY,
    work_unit_id TEXT NOT NULL REFERENCES work_units(id),
    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
    attempt_number INTEGER NOT NULL,
    worker_id TEXT,
    claim_token TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    retry_after_seconds INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scheduler_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
    work_unit_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    worker_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    active_job_id TEXT,
    active_work_unit_id TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def initialize_postgres_scheduler_schema(connection) -> None:
    with connection.transaction():
        connection.execute(SCHEMA_SQL)


class PostgresSchedulerStore:
    def __init__(self, dsn: str) -> None:
        self.connection = psycopg.connect(dsn, row_factory=dict_row)

    def close(self) -> None:
        self.connection.close()

    def clear_for_tests(self) -> None:
        with self.connection.transaction():
            self.connection.execute("DELETE FROM work_units")
            self.connection.execute("DELETE FROM translation_jobs")
```

Move mapping helpers in `persistent_jobs.py` from sqlite-row-specific names to mapping-compatible helpers:

```python
def _job_from_mapping(row) -> PersistentTranslationJob:
    ...

def _work_unit_from_mapping(row) -> PersistentWorkUnit:
    ...
```

Keep `_job_from_row = _job_from_mapping` and `_work_unit_from_row = _work_unit_from_mapping` compatibility wrappers.

- [ ] **Step 4: Implement PostgreSQL create/add/claim**

Add to `PostgresSchedulerStore`:

```python
    def create_job(self, **kwargs) -> PersistentTranslationJob:
        row = self.connection.execute(
            """
            INSERT INTO translation_jobs (
                id, order_id, user_id, file_id, file_name, document_kind,
                source_object_key, source_language, target_language,
                adapter_version, prompt_version, pricing_snapshot_id,
                translation_policy, status
            )
            VALUES (
                %(id)s, %(order_id)s, %(user_id)s, %(file_id)s, %(file_name)s,
                %(document_kind)s, %(source_object_key)s, %(source_language)s,
                %(target_language)s, %(adapter_version)s, %(prompt_version)s,
                %(pricing_snapshot_id)s, %(translation_policy)s, %(status)s
            )
            RETURNING *
            """,
            {
                **kwargs,
                "id": f"job-{uuid4().hex}",
                "source_object_key": kwargs.get("source_object_key") or kwargs["file_id"],
                "translation_policy": kwargs.get("translation_policy"),
                "status": PersistentTranslationJobStatus.QUEUED.value,
            },
        ).fetchone()
        self.connection.commit()
        return _job_from_mapping(row)

    def claim_next_scheduled_work_unit(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        limits: SchedulerLimits,
    ) -> SchedulerClaim | None:
        with self.connection.transaction():
            row = self.connection.execute(
                """
                SELECT wu.*
                FROM work_units wu
                JOIN translation_jobs tj ON tj.id = wu.job_id
                WHERE tj.status IN ('queued', 'translating')
                  AND tj.cancel_requested_at IS NULL
                  AND wu.status IN ('pending', 'failed_retryable')
                  AND wu.available_at <= now()
                  AND (wu.lease_until IS NULL OR wu.lease_until <= now())
                ORDER BY tj.priority DESC, tj.created_at, wu.sequence
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            claim_token = uuid4().hex
            updated = self.connection.execute(
                """
                UPDATE work_units
                SET status = 'translating',
                    worker_id = %(worker_id)s,
                    claim_token = %(claim_token)s,
                    lease_until = now() + (%(lease_seconds)s || ' seconds')::interval,
                    attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, now()),
                    updated_at = now()
                WHERE id = %(id)s
                RETURNING *
                """,
                {
                    "worker_id": worker_id,
                    "claim_token": claim_token,
                    "lease_seconds": max(1, lease_seconds),
                    "id": row["id"],
                },
            ).fetchone()
            self.connection.execute(
                """
                UPDATE translation_jobs
                SET status = 'translating', updated_at = now()
                WHERE id = %(job_id)s
                """,
                {"job_id": updated["job_id"]},
            )
        return SchedulerClaim(
            job_id=updated["job_id"],
            work_unit_id=updated["id"],
            worker_id=worker_id,
            claim_token=claim_token,
            lease_until=updated["lease_until"],
            attempt_number=updated["attempt_count"],
            source_object_key=updated["source_object_key"],
        )
```

Implement `add_work_units`, `list_work_units`, `get_job`, and `get_work_unit` with the same return dataclasses as the SQLite store.

- [ ] **Step 5: Run full local tests and optional PostgreSQL tests**

Run local:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: PASS with PostgreSQL tests skipped when `TEST_POSTGRES_DSN` is unset.

If Docker Postgres is running, run:

```bash
TEST_POSTGRES_DSN=postgresql://translator:translator@localhost:5432/translator PYTHONPATH=src python3 -m unittest tests/test_postgres_scheduler.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/translator_service/postgres_scheduler.py src/translator_service/persistent_jobs.py tests/test_postgres_scheduler.py
git commit -m "Add Postgres scheduler repository"
```

## Task 7: Worker CLI And Config

**Files:**

- Modify: `src/translator_service/config.py`
- Modify: `src/translator_service/worker.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write config tests**

Add to `tests/test_config.py`:

```python
    def test_scheduler_settings_have_safe_defaults(self):
        settings = Settings()

        self.assertEqual(settings.scheduler_backend, "sqlite")
        self.assertEqual(settings.scheduler_lease_seconds, 300)
        self.assertEqual(settings.scheduler_poll_seconds, 2.0)
        self.assertEqual(settings.scheduler_retry_base_delay_seconds, 30)
        self.assertEqual(settings.scheduler_retry_max_delay_seconds, 600)
```

- [ ] **Step 2: Run config test to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_config.py
```

Expected: FAIL because scheduler settings do not exist.

- [ ] **Step 3: Add scheduler settings**

In `src/translator_service/config.py`, add fields:

```python
    scheduler_backend: str = os.getenv("SCHEDULER_BACKEND", "sqlite")
    postgres_dsn: str = os.getenv(
        "POSTGRES_DSN",
        "postgresql://translator:translator@localhost:5432/translator",
    )
    scheduler_lease_seconds: int = field(
        default_factory=lambda: max(1, int(os.getenv("SCHEDULER_LEASE_SECONDS", "300")))
    )
    scheduler_poll_seconds: float = field(
        default_factory=lambda: max(0.1, float(os.getenv("SCHEDULER_POLL_SECONDS", "2.0")))
    )
    scheduler_retry_base_delay_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SCHEDULER_RETRY_BASE_DELAY_SECONDS", "30")),
        )
    )
    scheduler_retry_max_delay_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SCHEDULER_RETRY_MAX_DELAY_SECONDS", "600")),
        )
    )
```

- [ ] **Step 4: Replace worker CLI stub**

In `src/translator_service/worker.py`, replace the current `main()` body with:

```python
def main() -> None:
    from translator_service.bot.runtime import build_deepseek_translator
    from translator_service.config import Settings
    from translator_service.file_storage import LocalObjectStorage
    from translator_service.persistent_jobs import SQLiteTranslationJobStore
    from translator_service.scheduler import SchedulerLimits
    from translator_service.scheduler_runner import run_scheduler_once

    settings = Settings()
    storage = LocalObjectStorage(settings.object_storage_root)
    store = SQLiteTranslationJobStore(settings.persistent_jobs_db_path)
    translator = build_deepseek_translator(settings)
    try:
        while True:
            run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker:local",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=settings.translation_max_parallel_units,
                ),
                lease_seconds=settings.scheduler_lease_seconds,
            )
            time.sleep(settings.scheduler_poll_seconds)
    finally:
        store.close()
```

- [ ] **Step 5: Run compile and config tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_config.py
PYTHONPATH=src python3 -m compileall src
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/translator_service/config.py src/translator_service/worker.py src/translator_service/bot/runtime.py tests/test_config.py
git commit -m "Wire scheduler settings into worker CLI"
```

## Task 8: Telegram Persistent Path Uses Scheduler Runner

**Files:**

- Modify: `src/translator_service/bot_translation_service.py`
- Modify: `tests/test_bot_translation_service.py`

- [ ] **Step 1: Write behavior test for scheduler-backed confirmation**

Add to `tests/test_bot_translation_service.py` near the persistent confirmation tests:

```python
    def test_persistent_confirmation_uses_scheduler_runner_for_stored_work(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                file_storage=storage,
                persistent_job_store=persistent_store,
                use_scheduler_runner=True,
            )
            service.remember_upload(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                document_kind=DocumentKind.TXT,
                source_language="en",
                target_language="uk",
            )

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.\n\n[uk] Two.")
```

- [ ] **Step 2: Run bot service tests to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_bot_translation_service.py
```

Expected: FAIL because `use_scheduler_runner` does not exist.

- [ ] **Step 3: Add scheduler runner option to service**

In `BotTranslationService.__init__`, add:

```python
        use_scheduler_runner: bool = False,
```

Store:

```python
        self._use_scheduler_runner = use_scheduler_runner
```

In `_confirm_persistent_translation`, before direct sequential or parallel execution:

```python
        if self._use_scheduler_runner:
            return self._run_scheduler_backed_persistent_translation(
                document_kind=document_kind,
                pending=pending,
                translator=translator,
                progress_callback=progress_with_logging,
                cancellation_token=cancellation_token,
                job_id=plan.job.id,
                total_fragments=total_fragments,
                run_logger=run_logger,
            )
```

Add method:

```python
    def _run_scheduler_backed_persistent_translation(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None,
        cancellation_token: CancellationToken,
        job_id: str,
        total_fragments: int,
        run_logger: TranslationRunLogger | None,
    ) -> TranslationJob:
        assert self._file_storage is not None
        assert self._persistent_job_store is not None
        from translator_service.scheduler import SchedulerLimits
        from translator_service.scheduler_runner import run_scheduler_once

        while True:
            if cancellation_token.is_cancelled:
                self._persistent_job_store.cancel_job(job_id)
                break
            summary = run_scheduler_once(
                store=self._persistent_job_store,
                storage=self._file_storage,
                worker_id=f"telegram:{pending.user_telegram_id}",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=self._max_parallel_work_units,
                ),
                lease_seconds=300,
            )
            if summary.completed_units == 0 and summary.failed_units == 0:
                break

        persisted = self._persistent_job_store.get_job(job_id)
        partial = persisted.status is not PersistentTranslationJobStatus.READY
        result_status = (
            TranslationJobStatus.CANCELLED
            if cancellation_token.is_cancelled
            else TranslationJobStatus.READY
        )
        result_job = self._build_persistent_result_job(
            document_kind=document_kind,
            pending=pending,
            job_id=job_id,
            partial=partial,
            status=result_status,
        )
        _finish_run_logger(
            run_logger,
            status=result_job.status.value,
            result_file_name=result_job.result_file_name,
            error_message=result_job.error_message,
        )
        return result_job
```

Use the existing direct path as fallback until the scheduler-backed path passes all tests.

- [ ] **Step 4: Run bot translation tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_bot_translation_service.py tests/test_scheduler_runner.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/translator_service/bot_translation_service.py tests/test_bot_translation_service.py
git commit -m "Route persistent bot translations through scheduler runner"
```

## Task 9: Verification And Release Notes

**Files:**

- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-08-production-scheduler-design.md` if implementation discoveries require a correction.

- [ ] **Step 1: Document scheduler runtime settings**

Add to `README.md` under runtime configuration:

```markdown
### Scheduler Runtime

The production scheduler is PostgreSQL-first. `SCHEDULER_BACKEND=sqlite` keeps
local development on the SQLite adapter; `SCHEDULER_BACKEND=postgres` uses the
psycopg-backed repository and the same scheduler contract.

Useful settings:

- `SCHEDULER_LEASE_SECONDS`: claim lease duration for one work unit.
- `SCHEDULER_POLL_SECONDS`: worker sleep interval when no work is due.
- `SCHEDULER_RETRY_BASE_DELAY_SECONDS`: first retry backoff.
- `SCHEDULER_RETRY_MAX_DELAY_SECONDS`: maximum retry backoff.
- `POSTGRES_DSN`: PostgreSQL connection string for production scheduler state.

Redis is not required for scheduler correctness. If a notification layer is
added, workers must still be able to recover by scanning due PostgreSQL rows.
```

- [ ] **Step 2: Run full verification**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
git diff --check
```

Expected: all commands pass.

- [ ] **Step 3: Commit docs**

Run:

```bash
git add README.md docs/superpowers/specs/2026-05-08-production-scheduler-design.md
git commit -m "Document scheduler runtime settings"
```

## Execution Notes

- Keep old public methods such as `claim_next_work_unit`, `complete_work_unit`,
  `fail_work_unit`, `cancel_job`, and `resume_job` working until every caller is
  moved to scheduler methods.
- Do not delete the in-memory translation job path in this plan.
- Do not add Redis-backed queue behavior in this plan.
- Before touching files with user changes, inspect `git diff -- <path>` and work
  with the existing edits.
