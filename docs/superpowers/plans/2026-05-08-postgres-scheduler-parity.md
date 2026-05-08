# Postgres Scheduler Parity Implementation Plan


**Goal:** Make the PostgreSQL scheduler store usable by the same worker and scheduler runner paths as the SQLite scheduler store.

**Architecture:** Keep SQLite as the behavioral reference and extend `PostgresSchedulerStore` with the runtime methods the worker and runner already call. Add opt-in PostgreSQL integration tests for real database behavior, plus non-DSN contract tests so local CI still catches missing methods. After store parity, add a small worker store factory that honors `SCHEDULER_BACKEND`.

**Tech Stack:** Python 3.13, `unittest`, `psycopg`, PostgreSQL 16, existing scheduler dataclasses and local object storage.

---

## File Structure

- Modify `src/translator_service/postgres_scheduler.py`: add completion, failure, output attachment, assembly status, event/attempt helpers, and expired lease recovery.
- Modify `tests/test_postgres_scheduler.py`: add non-DSN method contract tests and opt-in integration tests for complete/fail/assembly.
- Modify `src/translator_service/worker.py`: add `open_scheduler_store(settings)` and use it from `main()`.
- Modify `tests/test_worker.py`: test backend selection without requiring PostgreSQL.

## Task 1: Postgres Store Runtime Method Contract

- [ ] **Step 1: Write failing non-DSN contract test**

Add a test to `tests/test_postgres_scheduler.py`:

```python
class PostgresSchedulerContractTest(unittest.TestCase):
    def test_store_exposes_scheduler_runtime_methods(self):
        expected_methods = [
            "complete_claimed_work_unit",
            "fail_claimed_work_unit",
            "attach_job_output",
            "list_jobs_by_status",
            "mark_job_assembled",
            "list_work_unit_attempts",
            "list_scheduler_events",
            "recover_expired_leases",
        ]

        for method_name in expected_methods:
            self.assertTrue(
                callable(getattr(PostgresSchedulerStore, method_name, None)),
                method_name,
            )
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_postgres_scheduler.py
```

Expected: FAIL because several methods do not exist.

- [ ] **Step 3: Implement minimal method surface**

In `src/translator_service/postgres_scheduler.py`, add the methods named by the test with SQL implementations matching the SQLite store behavior. Use `ValueError(f"Stale work-unit claim: {work_unit_id}")` for stale claim completion/failure.

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_postgres_scheduler.py
```

Expected: OK with the integration class skipped when `TEST_POSTGRES_DSN` is unset.

- [ ] **Step 5: Commit**

```bash
git add src/translator_service/postgres_scheduler.py tests/test_postgres_scheduler.py
git commit -m "Complete Postgres scheduler store contract"
```

## Task 2: Opt-In Postgres Completion And Retry Behavior

- [ ] **Step 1: Write opt-in integration tests**

Add tests under `PostgresSchedulerStoreTest`:

```python
    def test_complete_claimed_unit_moves_job_to_assembling(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        completed = self.store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text="[uk] First paragraph",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=1,
            cache_miss_tokens=9,
        )

        persisted_job = self.store.get_job(job.id)
        events = self.store.list_scheduler_events(job.id)
        self.assertEqual(completed.status.value, "translated")
        self.assertEqual(persisted_job.status.value, "assembling")
        self.assertEqual(events[-1].event_type, "work_unit_completed")

    def test_retryable_failure_records_attempt_and_releases_claim(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = self.store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(job.id)
        self.assertEqual(failed.status.value, "failed_retryable")
        self.assertIsNone(failed.claim_token)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(events[-1].event_type, "work_unit_retry_scheduled")
```

Add helper:

```python
    def _create_txt_job_with_unit(self):
        job = self.store.create_job(...)
        self.store.add_work_units(job.id, [WorkUnitPlan(...)])
        return job
```

- [ ] **Step 2: Run opt-in test without DSN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_postgres_scheduler.py
```

Expected: OK with PostgreSQL tests skipped locally.

- [ ] **Step 3: Commit tests/implementation if not already committed**

```bash
git add src/translator_service/postgres_scheduler.py tests/test_postgres_scheduler.py
git commit -m "Verify Postgres scheduler completion and retry"
```

## Task 3: Worker Scheduler Backend Switch

- [ ] **Step 1: Write failing worker backend test**

Add to `tests/test_worker.py`:

```python
    def test_open_scheduler_store_uses_sqlite_backend(self):
        from translator_service.config import Settings
        from translator_service.worker import open_scheduler_store

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
            )
            store = open_scheduler_store(settings)
            self.addCleanup(store.close)

            self.assertIsInstance(store, SQLiteTranslationJobStore)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_worker.py
```

Expected: FAIL because `open_scheduler_store` does not exist.

- [ ] **Step 3: Implement backend factory**

Add to `src/translator_service/worker.py`:

```python
def open_scheduler_store(settings):
    if settings.scheduler_backend == "sqlite":
        return SQLiteTranslationJobStore(settings.persistent_jobs_db_path)
    if settings.scheduler_backend == "postgres":
        from translator_service.postgres_scheduler import (
            PostgresSchedulerStore,
            initialize_postgres_scheduler_schema,
        )

        store = PostgresSchedulerStore(settings.postgres_dsn)
        initialize_postgres_scheduler_schema(store.connection)
        return store
    raise ValueError(f"Unsupported scheduler backend: {settings.scheduler_backend}")
```

Update `main()` to call `open_scheduler_store(settings)`.

- [ ] **Step 4: Run focused verification**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests/test_worker.py tests/test_postgres_scheduler.py
PYTHONPATH=src python3 -m compileall src
```

Expected: PASS with PostgreSQL integration tests skipped when `TEST_POSTGRES_DSN` is unset.

- [ ] **Step 5: Commit**

```bash
git add src/translator_service/worker.py tests/test_worker.py
git commit -m "Select scheduler store backend in worker"
```

## Task 4: Final Verification

- [ ] **Step 1: Run full local suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
git diff --check
```

Expected: PASS with `TEST_POSTGRES_DSN` tests skipped when the variable is unset.

- [ ] **Step 2: Report remaining caveat**

If `TEST_POSTGRES_DSN` is unset, explicitly report that real PostgreSQL integration tests were skipped locally.
