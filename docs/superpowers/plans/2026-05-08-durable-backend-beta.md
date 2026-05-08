# Durable Backend Beta Implementation Plan


**Goal:** Move the Telegram translation prototype to a durable server backend where uploads, jobs, work units, progress, partial outputs, final outputs, and resume state survive Ctrl+C, bot restart, worker crash, network loss, and machine restart.

**Architecture:** The Telegram bot becomes a thin UI adapter. Confirmed translation work is persisted as jobs and ordered work units, then executed by one or more worker processes that claim units through durable leases and write every completed unit back to storage before continuing. PostgreSQL is the beta source of truth on the server; SQLite remains a local development fallback.

**Tech Stack:** Python 3.13, aiogram, FastAPI, PostgreSQL 16, psycopg 3, Docker Compose, local filesystem object storage for closed beta, existing DeepSeek client, existing document adapters.

---

## Current Starting Point

- The repository already has a minimal backend skeleton: `Dockerfile`, `docker-compose.yml`, `src/translator_service/api.py`, `src/translator_service/worker.py`, `src/translator_service/persistent_jobs.py`, `src/translator_service/file_storage.py`, and `.env.*.example` files.
- `SQLiteTranslationJobStore` persists jobs and work units locally, but server Compose already includes PostgreSQL and the Python code does not yet use PostgreSQL as a job store.
- `worker.py` can process one persistent work unit when the caller supplies a job id and source loader, but the CLI entrypoint is still a placeholder and does not run a durable worker loop.
- `bot_translation_service.py` can run the persistent path for TXT, but confirmation still executes work inside the Telegram process. Server beta requires queue-only confirmation and worker-side execution.
- `config.py` exposes only a small settings subset. Environment files use `DATABASE_URL`, while code currently has no database DSN setting. The backend needs one canonical setting.
- `docker-compose.yml` starts API, bot, worker, PostgreSQL, and Redis, but object storage and runtime logs are not mounted into durable volumes.

## File Structure

Create or modify these files:

- Modify `src/translator_service/config.py`: add backend mode, database DSN, worker polling, lease, storage, and startup validation settings.
- Modify `.env.example`, `.env.dev.example`, `.env.stable.example`, `.env.beta.example`: align environment variable names with code and document beta-safe defaults.
- Create `src/translator_service/job_store.py`: define the protocol shared by SQLite and PostgreSQL stores.
- Modify `src/translator_service/persistent_jobs.py`: keep SQLite behavior and make it conform to the shared protocol.
- Create `src/translator_service/postgres_jobs.py`: PostgreSQL implementation for durable server beta.
- Create `src/translator_service/job_store_factory.py`: choose SQLite or PostgreSQL from settings.
- Modify `src/translator_service/worker.py`: replace placeholder CLI with a polling worker loop.
- Modify `src/translator_service/bot_translation_service.py`: add worker-backed confirmation mode that creates persistent jobs and returns queued status instead of translating inline.
- Modify `src/translator_service/bot/runtime.py`: show queued/running/resumable jobs from persisted state and keep existing in-memory path available for local development.
- Modify `src/translator_service/api.py`: add readiness checks for database and object storage.
- Modify `docker-compose.yml`: make the server beta stack persistent and restartable.
- Create `docs/deployment/server-beta.md`: operator runbook for closed beta deployment, restart, logs, backup, and recovery.
- Add tests in `tests/test_config.py`, `tests/test_persistent_jobs.py`, `tests/test_postgres_jobs.py`, `tests/test_worker.py`, `tests/test_bot_translation_service.py`, `tests/test_bot_runtime.py`, and `tests/test_api.py`.

---

### Task 1: Backend Settings And Startup Validation

**Files:**
- Modify: `src/translator_service/config.py`
- Modify: `.env.example`
- Modify: `.env.dev.example`
- Modify: `.env.stable.example`
- Modify: `.env.beta.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing settings tests**

Add these tests to `tests/test_config.py`:

```python
import os
import unittest
from unittest.mock import patch

from translator_service.config import Settings, validate_server_settings


class BackendSettingsTests(unittest.TestCase):
    def test_reads_backend_settings_from_environment(self):
        env = {
            "JOB_STORE_BACKEND": "postgres",
            "POSTGRES_DSN": "postgresql://translator:secret@postgres:5432/translator",
            "TRANSLATION_EXECUTION_MODE": "worker",
            "WORKER_POLL_SECONDS": "2.5",
            "WORK_UNIT_LEASE_SECONDS": "900",
            "OBJECT_STORAGE_ROOT": "/data/object-storage",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        self.assertEqual(settings.job_store_backend, "postgres")
        self.assertEqual(
            settings.postgres_dsn,
            "postgresql://translator:secret@postgres:5432/translator",
        )
        self.assertEqual(settings.translation_execution_mode, "worker")
        self.assertEqual(settings.worker_poll_seconds, 2.5)
        self.assertEqual(settings.work_unit_lease_seconds, 900)
        self.assertEqual(settings.object_storage_root, "/data/object-storage")

    def test_server_validation_requires_postgres_for_worker_mode(self):
        settings = Settings(
            job_store_backend="sqlite",
            translation_execution_mode="worker",
        )

        with self.assertRaisesRegex(ValueError, "JOB_STORE_BACKEND=postgres"):
            validate_server_settings(settings)

    def test_server_validation_accepts_postgres_worker_mode(self):
        settings = Settings(
            job_store_backend="postgres",
            translation_execution_mode="worker",
            postgres_dsn="postgresql://translator:secret@postgres:5432/translator",
            object_storage_root="/data/object-storage",
        )

        validate_server_settings(settings)
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_config.BackendSettingsTests
```

Expected: failure because `Settings` has no `job_store_backend`, `postgres_dsn`, `translation_execution_mode`, `worker_poll_seconds`, `work_unit_lease_seconds`, or `validate_server_settings`.

- [ ] **Step 3: Implement settings**

Update `src/translator_service/config.py` to keep the existing defaults and add server backend settings:

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    service_name: str = os.getenv("SERVICE_NAME", "DeepSeek Document Translator")
    environment: str = os.getenv("ENVIRONMENT", "development")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    object_storage_root: str = os.getenv("OBJECT_STORAGE_ROOT", "var/object-storage")
    persistent_jobs_db_path: str = os.getenv(
        "PERSISTENT_JOBS_DB_PATH",
        "var/jobs.sqlite3",
    )
    job_store_backend: str = os.getenv("JOB_STORE_BACKEND", "sqlite")
    postgres_dsn: str = os.getenv(
        "POSTGRES_DSN",
        os.getenv("DATABASE_URL", "postgresql://translator:translator@localhost:5432/translator"),
    )
    translation_execution_mode: str = os.getenv("TRANSLATION_EXECUTION_MODE", "inline")
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "3"))
    work_unit_lease_seconds: int = int(os.getenv("WORK_UNIT_LEASE_SECONDS", "900"))
    worker_id: str = os.getenv("WORKER_ID", "worker-local")


def validate_server_settings(settings: Settings) -> None:
    if settings.translation_execution_mode == "worker":
        if settings.job_store_backend != "postgres":
            raise ValueError(
                "TRANSLATION_EXECUTION_MODE=worker requires JOB_STORE_BACKEND=postgres"
            )
        if not settings.postgres_dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("POSTGRES_DSN must be a PostgreSQL DSN")
    if not settings.object_storage_root:
        raise ValueError("OBJECT_STORAGE_ROOT is required")
```

- [ ] **Step 4: Align environment examples**

In `.env.example`, use server-safe names:

```dotenv
SERVICE_NAME=FolioLoom
ENVIRONMENT=server-beta
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
JOB_STORE_BACKEND=postgres
POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator
TRANSLATION_EXECUTION_MODE=worker
OBJECT_STORAGE_ROOT=/data/object-storage
PERSISTENT_JOBS_DB_PATH=var/jobs.sqlite3
WORKER_POLL_SECONDS=3
WORK_UNIT_LEASE_SECONDS=900
MAX_UPLOAD_MB=50
```

In `.env.dev.example`, keep local defaults:

```dotenv
SERVICE_NAME=FolioLoom Dev
ENVIRONMENT=development
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
JOB_STORE_BACKEND=sqlite
POSTGRES_DSN=postgresql://translator_dev:translator_dev@localhost:5432/translator_dev
TRANSLATION_EXECUTION_MODE=inline
OBJECT_STORAGE_ROOT=var/dev-object-storage
PERSISTENT_JOBS_DB_PATH=var/dev-jobs.sqlite3
WORKER_POLL_SECONDS=3
WORK_UNIT_LEASE_SECONDS=900
MAX_UPLOAD_MB=50
```

In `.env.stable.example`, use a stable bot name and keep worker mode ready:

```dotenv
SERVICE_NAME=FolioLoom Stable
ENVIRONMENT=stable
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
JOB_STORE_BACKEND=postgres
POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator
TRANSLATION_EXECUTION_MODE=worker
OBJECT_STORAGE_ROOT=/data/object-storage
PERSISTENT_JOBS_DB_PATH=var/stable-jobs.sqlite3
WORKER_POLL_SECONDS=3
WORK_UNIT_LEASE_SECONDS=900
MAX_UPLOAD_MB=50
```

In `.env.beta.example`, use isolated beta names:

```dotenv
SERVICE_NAME=FolioLoom Beta
ENVIRONMENT=beta
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
JOB_STORE_BACKEND=postgres
POSTGRES_DSN=postgresql://translator_beta:translator_beta@postgres:5432/translator_beta
TRANSLATION_EXECUTION_MODE=worker
OBJECT_STORAGE_ROOT=/data/object-storage
PERSISTENT_JOBS_DB_PATH=var/beta-jobs.sqlite3
WORKER_POLL_SECONDS=3
WORK_UNIT_LEASE_SECONDS=900
MAX_UPLOAD_MB=50
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_config
```

Expected: all config tests pass.

Commit:

```bash
git add src/translator_service/config.py .env.example .env.dev.example .env.stable.example .env.beta.example tests/test_config.py
git commit -m "feat: add durable backend settings"
```

---

### Task 2: Shared Job Store Protocol

**Files:**
- Create: `src/translator_service/job_store.py`
- Modify: `src/translator_service/persistent_jobs.py`
- Test: `tests/test_persistent_jobs.py`

- [ ] **Step 1: Write protocol conformance test**

Add this test to `tests/test_persistent_jobs.py`:

```python
from translator_service.job_store import TranslationJobStore


class JobStoreProtocolTests(unittest.TestCase):
    def test_sqlite_store_satisfies_translation_job_store_protocol(self):
        store: TranslationJobStore = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)

        job = store.create_job(
            order_id="order-1",
            user_id="user-1",
            file_id="file-1",
            file_name="book.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="prompt-v1",
            pricing_snapshot_id="price-v1",
            source_object_key="original/file-1.txt",
        )

        self.assertEqual(store.get_job(job.id).id, job.id)
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs.JobStoreProtocolTests
```

Expected: failure because `translator_service.job_store` does not exist.

- [ ] **Step 3: Create the protocol**

Create `src/translator_service/job_store.py`:

```python
from typing import Protocol

from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentTranslationJob,
    PersistentWorkUnit,
    WorkUnitPlan,
)


class TranslationJobStore(Protocol):
    def close(self) -> None:
        ...

    def create_job(
        self,
        *,
        order_id: str,
        user_id: str,
        file_id: str,
        file_name: str,
        document_kind: str,
        source_language: str,
        target_language: str,
        adapter_version: str,
        prompt_version: str,
        pricing_snapshot_id: str,
        source_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        ...

    def attach_job_output(
        self,
        job_id: str,
        *,
        partial_object_key: str | None = None,
        final_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        ...

    def get_job(self, job_id: str) -> PersistentTranslationJob | None:
        ...

    def add_work_units(
        self,
        job_id: str,
        work_units: list[WorkUnitPlan],
    ) -> list[PersistentWorkUnit]:
        ...

    def list_work_units(self, job_id: str) -> list[PersistentWorkUnit]:
        ...

    def claim_next_work_unit(
        self,
        job_id: str,
        *,
        worker_id: str,
    ) -> PersistentWorkUnit | None:
        ...

    def complete_work_unit(
        self,
        work_unit_id: str,
        *,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> PersistentWorkUnit:
        ...

    def fail_work_unit(
        self,
        work_unit_id: str,
        *,
        error_message: str,
        retry_count: int,
    ) -> PersistentWorkUnit:
        ...

    def cancel_job(self, job_id: str) -> PersistentTranslationJob:
        ...

    def resume_job(self, job_id: str) -> PersistentTranslationJob:
        ...

    def get_usage_summary(self, job_id: str) -> JobUsageSummary:
        ...
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs
```

Expected: all persistent job tests pass.

Commit:

```bash
git add src/translator_service/job_store.py tests/test_persistent_jobs.py
git commit -m "refactor: define translation job store protocol"
```

---

### Task 3: PostgreSQL Job Store

**Files:**
- Create: `src/translator_service/postgres_jobs.py`
- Create: `tests/test_postgres_jobs.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write PostgreSQL integration tests**

Create `tests/test_postgres_jobs.py`:

```python
import os
import unittest

from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    WorkUnitPlan,
)
from translator_service.postgres_jobs import PostgreSQLTranslationJobStore


@unittest.skipUnless(os.getenv("TEST_POSTGRES_DSN"), "TEST_POSTGRES_DSN is not set")
class PostgreSQLTranslationJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgreSQLTranslationJobStore(os.environ["TEST_POSTGRES_DSN"])
        self.addCleanup(self.store.close)
        self.store.reset_schema_for_tests()

    def test_creates_claims_completes_and_summarizes_job(self):
        job = self.store.create_job(
            order_id="order-1",
            user_id="user-1",
            file_id="file-1",
            file_name="book.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="prompt-v1",
            pricing_snapshot_id="price-v1",
            source_object_key="original/file-1.txt",
        )
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("block-1",),
                    source_object_key="work/job-1/unit-1.txt",
                    source_text_hash="hash-1",
                    prompt_tier="default",
                    source_language="en",
                    target_language="uk",
                )
            ],
        )

        claimed = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.assertEqual(claimed.status, PersistentWorkUnitStatus.TRANSLATING)

        completed = self.store.complete_work_unit(
            claimed.id,
            translated_text="Привіт",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=2,
            cache_miss_tokens=8,
        )
        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(
            self.store.get_job(job.id).status,
            PersistentTranslationJobStatus.READY,
        )
        self.assertEqual(self.store.get_usage_summary(job.id).total_tokens, 15)
```

- [ ] **Step 2: Run test and verify skip or failure**

Run without PostgreSQL:

```bash
PYTHONPATH=src python3 -m unittest tests.test_postgres_jobs
```

Expected: skipped when `TEST_POSTGRES_DSN` is absent.

Run with PostgreSQL available:

```bash
TEST_POSTGRES_DSN=postgresql://translator:translator@localhost:5432/translator PYTHONPATH=src python3 -m unittest tests.test_postgres_jobs
```

Expected: failure because `translator_service.postgres_jobs` does not exist.

- [ ] **Step 3: Implement PostgreSQL store**

Create `src/translator_service/postgres_jobs.py` with the same public behavior as `SQLiteTranslationJobStore`. Use psycopg row dictionaries and PostgreSQL transactions. The claim query must lock one pending unit atomically:

```sql
SELECT id
FROM work_units
WHERE job_id = %s AND status = 'pending'
ORDER BY sequence
FOR UPDATE SKIP LOCKED
LIMIT 1
```

The implementation must:

- create the same `translation_jobs` and `work_units` tables with PostgreSQL types;
- convert rows into the existing dataclasses from `persistent_jobs.py`;
- use `ON CONFLICT DO NOTHING` for schema creation only;
- set job status to `translating` when a unit is claimed;
- set job status to `ready` only when no pending, translating, or failed units remain;
- expose `reset_schema_for_tests()` only for integration tests.

- [ ] **Step 4: Add psycopg dependency check**

Ensure `pyproject.toml` includes:

```toml
"psycopg[binary]>=3.2",
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs tests.test_postgres_jobs
```

Expected: SQLite tests pass and PostgreSQL tests skip unless `TEST_POSTGRES_DSN` is set.

Commit:

```bash
git add src/translator_service/postgres_jobs.py tests/test_postgres_jobs.py pyproject.toml
git commit -m "feat: add postgres translation job store"
```

---

### Task 4: Job Store Factory

**Files:**
- Create: `src/translator_service/job_store_factory.py`
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Write factory tests**

Add this to `tests/test_bot_runtime.py` or create `tests/test_job_store_factory.py`:

```python
import unittest
from unittest.mock import patch

from translator_service.config import Settings
from translator_service.job_store_factory import create_translation_job_store
from translator_service.persistent_jobs import SQLiteTranslationJobStore


class JobStoreFactoryTests(unittest.TestCase):
    def test_creates_sqlite_store_for_local_development(self):
        settings = Settings(
            job_store_backend="sqlite",
            persistent_jobs_db_path=":memory:",
        )

        store = create_translation_job_store(settings)
        self.addCleanup(store.close)

        self.assertIsInstance(store, SQLiteTranslationJobStore)

    def test_creates_postgres_store_for_server_backend(self):
        settings = Settings(
            job_store_backend="postgres",
            postgres_dsn="postgresql://translator:translator@postgres:5432/translator",
        )

        with patch("translator_service.job_store_factory.PostgreSQLTranslationJobStore") as cls:
            create_translation_job_store(settings)

        cls.assert_called_once_with(settings.postgres_dsn)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_job_store_factory
```

Expected: failure because `job_store_factory.py` does not exist.

- [ ] **Step 3: Implement factory**

Create `src/translator_service/job_store_factory.py`:

```python
from translator_service.config import Settings
from translator_service.job_store import TranslationJobStore
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.postgres_jobs import PostgreSQLTranslationJobStore


def create_translation_job_store(settings: Settings) -> TranslationJobStore:
    if settings.job_store_backend == "sqlite":
        return SQLiteTranslationJobStore(settings.persistent_jobs_db_path)
    if settings.job_store_backend == "postgres":
        return PostgreSQLTranslationJobStore(settings.postgres_dsn)
    raise ValueError(f"Unsupported JOB_STORE_BACKEND: {settings.job_store_backend}")
```

- [ ] **Step 4: Wire runtime construction through factory**

In `src/translator_service/bot/runtime.py`, replace direct `SQLiteTranslationJobStore(config.persistent_jobs_db_path)` construction with:

```python
from translator_service.job_store_factory import create_translation_job_store


persistent_job_store = create_translation_job_store(settings)
```

Keep the existing tests that assert local SQLite wiring by using `JOB_STORE_BACKEND=sqlite`.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime tests.test_config
```

Expected: all tests pass.

Commit:

```bash
git add src/translator_service/job_store_factory.py src/translator_service/bot/runtime.py tests/test_bot_runtime.py tests/test_job_store_factory.py
git commit -m "feat: select persistent job store from settings"
```

---

### Task 5: Durable Worker Loop

**Files:**
- Modify: `src/translator_service/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write worker loop tests**

Add this to `tests/test_worker.py`:

```python
from translator_service.worker import run_worker_tick


class WorkerLoopTests(unittest.TestCase):
    def test_worker_tick_processes_first_available_job(self):
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        storage = LocalObjectStorage(self._temp_dir.name)
        source = storage.put_bytes(
            kind=StoredFileKind.INTERMEDIATE,
            file_name="unit-1.txt",
            content_type="text/plain",
            content=b"Hello",
        )
        job = store.create_job(
            order_id="order-1",
            user_id="user-1",
            file_id="file-1",
            file_name="book.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="prompt-v1",
            pricing_snapshot_id="price-v1",
            source_object_key="original/file-1.txt",
        )
        store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("block-1",),
                    source_object_key=source.object_key,
                    source_text_hash="hash-1",
                    prompt_tier="default",
                    source_language="en",
                    target_language="uk",
                )
            ],
        )

        processed = run_worker_tick(
            store=store,
            storage=storage,
            worker_id="worker-a",
            translator=FakeTranslator("Привіт"),
        )

        self.assertEqual(processed, 1)
        self.assertEqual(store.list_work_units(job.id)[0].translated_text, "Привіт")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_worker.WorkerLoopTests
```

Expected: failure because `run_worker_tick` does not exist.

- [ ] **Step 3: Implement worker tick**

In `src/translator_service/worker.py`, add:

```python
def run_worker_tick(
    *,
    store: TranslationJobStore,
    storage: LocalObjectStorage,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
) -> int:
    processed = 0
    for job in store.list_claimable_jobs():
        completed = run_next_stored_text_work_unit(
            store=store,
            storage=storage,
            job_id=job.id,
            worker_id=worker_id,
            translator=translator,
        )
        if completed is not None:
            processed += 1
            break
    return processed
```

This step requires `list_claimable_jobs()` on both job stores. Add it to the protocol and stores with this rule:

```sql
status IN ('queued', 'translating', 'interrupted')
ORDER BY created_at, id
```

- [ ] **Step 4: Implement CLI loop**

Replace placeholder `main()` in `src/translator_service/worker.py`:

```python
def main() -> None:
    settings = Settings()
    validate_server_settings(settings)
    store = create_translation_job_store(settings)
    storage = LocalObjectStorage(settings.object_storage_root)
    translator = DeepSeekClient.from_environment()
    logger.info("Worker started: worker_id=%s", settings.worker_id)
    try:
        while True:
            processed = run_worker_tick(
                store=store,
                storage=storage,
                worker_id=settings.worker_id,
                translator=translator,
            )
            if processed == 0:
                time.sleep(settings.worker_poll_seconds)
    finally:
        store.close()
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_worker tests.test_persistent_jobs
```

Expected: worker and persistent job tests pass.

Commit:

```bash
git add src/translator_service/worker.py src/translator_service/job_store.py src/translator_service/persistent_jobs.py src/translator_service/postgres_jobs.py tests/test_worker.py tests/test_persistent_jobs.py
git commit -m "feat: run durable translation worker loop"
```

---

### Task 6: Queue-Only Telegram Confirmation Mode

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_translation_service.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Write service test for worker mode**

Add this test to `tests/test_bot_translation_service.py`:

```python
def test_worker_mode_confirmation_queues_job_without_inline_translation(self):
    with TemporaryDirectory() as temp_dir:
        storage = LocalObjectStorage(temp_dir)
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        service = BotTranslationService(
            object_storage=storage,
            persistent_job_store=store,
            translation_execution_mode="worker",
        )
        service.create_pending_translation(
            user_telegram_id=123,
            file_name="sample.txt",
            file_bytes=b"Hello world",
            source_language="en",
            target_language="uk",
        )

        translator = FakeTranslator("Привіт")
        job = service.confirm_pending_translation(
            user_telegram_id=123,
            translator=translator,
        )

        persisted = store.get_job(job.id)
        self.assertEqual(persisted.status.value, "queued")
        self.assertEqual(translator.calls, [])
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service.BotTranslationServiceTests.test_worker_mode_confirmation_queues_job_without_inline_translation
```

Expected: failure because `translation_execution_mode` is not accepted by the service.

- [ ] **Step 3: Add execution mode to service**

In `BotTranslationService.__init__`, add:

```python
translation_execution_mode: str = "inline",
```

Store it:

```python
self._translation_execution_mode = translation_execution_mode
```

In persistent confirmation, branch:

```python
if self._translation_execution_mode == "worker":
    return self._queue_persistent_txt_translation(pending=pending)
```

`_queue_persistent_txt_translation` must create the same persistent plan and return a `TranslationJob` with status text usable by the bot, without calling `run_next_stored_text_work_unit`.

- [ ] **Step 4: Wire runtime setting**

In `src/translator_service/bot/runtime.py`, pass:

```python
translation_execution_mode=settings.translation_execution_mode,
```

to `BotTranslationService`.

- [ ] **Step 5: Add bot text test for queued result**

Add a runtime test that confirms the user receives a queued/running message instead of a final file when `TRANSLATION_EXECUTION_MODE=worker`. The assertion should check that the message contains a localized equivalent of:

```text
Translation has started. You can leave the bot; progress is saved.
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service tests.test_bot_runtime
```

Expected: bot service and runtime tests pass.

Commit:

```bash
git add src/translator_service/bot_translation_service.py src/translator_service/bot/runtime.py tests/test_bot_translation_service.py tests/test_bot_runtime.py
git commit -m "feat: queue telegram translations for workers"
```

---

### Task 7: Crash Recovery And Lease Reclaim

**Files:**
- Modify: `src/translator_service/job_store.py`
- Modify: `src/translator_service/persistent_jobs.py`
- Modify: `src/translator_service/postgres_jobs.py`
- Test: `tests/test_persistent_jobs.py`
- Test: `tests/test_postgres_jobs.py`

- [x] **Step 1: Write crash recovery test**

Add this SQLite test:

```python
def test_reclaims_expired_translating_unit_after_worker_crash(self):
    store = SQLiteTranslationJobStore(":memory:")
    self.addCleanup(store.close)
    job = self._create_job(store)
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("block-1",),
                source_text_hash="hash-1",
                prompt_tier="default",
                source_language="en",
                target_language="uk",
            )
        ],
    )
    first = store.claim_next_work_unit(job.id, worker_id="worker-a")

    reclaimed = store.reclaim_stale_work_units(
        lease_seconds=0,
        worker_id="worker-b",
    )
    second = store.claim_next_work_unit(job.id, worker_id="worker-b")

    self.assertEqual(reclaimed, 1)
    self.assertEqual(first.id, second.id)
    self.assertEqual(second.worker_id, "worker-b")
```

- [x] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs.PersistentJobStoreTests.test_reclaims_expired_translating_unit_after_worker_crash
```

Expected: failure because `reclaim_stale_work_units` does not exist.

- [x] **Step 3: Implement stale lease reclaim**

Add to the protocol:

```python
def reclaim_stale_work_units(self, *, lease_seconds: int, worker_id: str) -> int:
    ...
```

Implement in SQLite and PostgreSQL:

- find `work_units.status = 'translating'`;
- compare `updated_at` or `started_at` with current time minus `lease_seconds`;
- set stale units back to `pending`;
- clear `worker_id`;
- update parent job to `queued`;
- return the number of reclaimed units.

- [x] **Step 4: Call reclaim from worker loop**

At the start of each `run_worker_tick`, call:

```python
store.reclaim_stale_work_units(
    lease_seconds=settings.work_unit_lease_seconds,
    worker_id=worker_id,
)
```

When `run_worker_tick` is used in tests, pass `lease_seconds` as an explicit parameter with default `900`.

- [x] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs tests.test_worker tests.test_postgres_jobs
```

Expected: SQLite tests pass and PostgreSQL tests skip without `TEST_POSTGRES_DSN`.

Commit:

```bash
git add src/translator_service/job_store.py src/translator_service/persistent_jobs.py src/translator_service/postgres_jobs.py src/translator_service/worker.py tests/test_persistent_jobs.py tests/test_postgres_jobs.py tests/test_worker.py
git commit -m "feat: reclaim stale translation work leases"
```

---

### Task 8: User Resume And Partial Download From Persistent State

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_translation_service.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Write resume service test**

Add:

```python
def test_resume_persistent_job_requeues_failed_and_translating_units(self):
    store = SQLiteTranslationJobStore(":memory:")
    self.addCleanup(store.close)
    service = BotTranslationService(
        persistent_job_store=store,
        translation_execution_mode="worker",
    )
    job = self._create_persistent_job_with_failed_unit(store, user_id="123")

    resumed = service.resume_persistent_translation(
        user_telegram_id=123,
        job_id=job.id,
    )

    self.assertEqual(resumed.status.value, "queued")
    self.assertEqual(store.list_work_units(job.id)[0].status.value, "pending")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service.BotTranslationServiceTests.test_resume_persistent_job_requeues_failed_and_translating_units
```

Expected: failure because service resume is not backed by worker-mode persistent state.

- [ ] **Step 3: Implement resume ownership check**

Add service method:

```python
def resume_persistent_translation(
    self,
    *,
    user_telegram_id: int,
    job_id: str,
) -> PersistentTranslationJob:
    assert self._persistent_job_store is not None
    job = self._persistent_job_store.get_job(job_id)
    if job is None:
        raise ValueError(f"Translation job does not exist: {job_id}")
    if job.user_id != str(user_telegram_id):
        raise PermissionError("Translation job belongs to another user")
    return self._persistent_job_store.resume_job(job_id)
```

- [ ] **Step 4: Add bot callbacks**

In runtime, add callbacks for:

- `resume:<job_id>`: calls `resume_persistent_translation`, then updates book card text;
- `download_partial:<job_id>`: assembles or returns the stored partial file;
- `download_final:<job_id>`: returns the final file if ready.

Each callback must verify ownership through the service method, not through button text.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service tests.test_bot_runtime
```

Expected: service and runtime tests pass.

Commit:

```bash
git add src/translator_service/bot_translation_service.py src/translator_service/bot/runtime.py tests/test_bot_translation_service.py tests/test_bot_runtime.py
git commit -m "feat: resume persistent translations from telegram"
```

---

### Task 9: Health And Readiness API

**Files:**
- Modify: `src/translator_service/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write readiness tests**

Create or extend `tests/test_api.py`:

```python
import unittest
from tempfile import TemporaryDirectory

from translator_service.api import health_payload, readiness_payload
from translator_service.config import Settings


class ApiHealthTests(unittest.TestCase):
    def test_health_payload_is_lightweight(self):
        payload = health_payload(Settings(service_name="FolioLoom"))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "FolioLoom")

    def test_readiness_checks_object_storage_path(self):
        with TemporaryDirectory() as temp_dir:
            payload = readiness_payload(
                Settings(
                    object_storage_root=temp_dir,
                    job_store_backend="sqlite",
                    persistent_jobs_db_path=":memory:",
                )
            )

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["object_storage"], "ok")
        self.assertEqual(payload["job_store"], "ok")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_api
```

Expected: failure because `readiness_payload` does not exist.

- [ ] **Step 3: Implement readiness**

In `src/translator_service/api.py`, add:

```python
def readiness_payload(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or Settings()
    Path(active_settings.object_storage_root).mkdir(parents=True, exist_ok=True)
    probe_path = Path(active_settings.object_storage_root) / ".ready"
    probe_path.write_text("ok", encoding="utf-8")
    probe_path.unlink(missing_ok=True)
    store = create_translation_job_store(active_settings)
    try:
        store.close()
    finally:
        pass
    return {
        "service": active_settings.service_name,
        "status": "ready",
        "object_storage": "ok",
        "job_store": "ok",
    }
```

Expose endpoint:

```python
@app.get("/ready")
def ready() -> dict[str, str]:
    return readiness_payload()
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_api tests.test_config
```

Expected: API and config tests pass.

Commit:

```bash
git add src/translator_service/api.py tests/test_api.py
git commit -m "feat: add backend readiness checks"
```

---

### Task 10: Server Docker Compose

**Files:**
- Modify: `docker-compose.yml`
- Create: `docker-compose.local.yml`
- Test: manual Docker Compose config validation

- [ ] **Step 1: Preserve local overrides**

Create `docker-compose.local.yml` for local development:

```yaml
services:
  api:
    env_file: .env.dev
    ports:
      - "8000:8000"

  bot:
    env_file: .env.dev

  worker:
    env_file: .env.dev
```

- [ ] **Step 2: Harden server compose**

Update `docker-compose.yml`:

```yaml
services:
  api:
    build: .
    command: uvicorn translator_service.api:create_app --factory --host 0.0.0.0 --port 8000
    env_file: .env
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - object-storage:/data/object-storage
      - run-logs:/data/run-logs
    depends_on:
      postgres:
        condition: service_healthy

  bot:
    build: .
    command: python -m translator_service.bot
    env_file: .env
    restart: unless-stopped
    volumes:
      - object-storage:/data/object-storage
      - run-logs:/data/run-logs
    depends_on:
      postgres:
        condition: service_healthy

  worker:
    build: .
    command: python -m translator_service.worker
    env_file: .env
    restart: unless-stopped
    volumes:
      - object-storage:/data/object-storage
      - run-logs:/data/run-logs
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: translator
      POSTGRES_USER: translator
      POSTGRES_PASSWORD: translator
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U translator -d translator"]
      interval: 5s
      timeout: 5s
      retries: 20
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data

volumes:
  postgres-data:
  object-storage:
  run-logs:
```

Redis is removed from the first server beta compose because the durable job table is the queue and source of truth.

- [ ] **Step 3: Validate Compose file**

Run:

```bash
docker compose config
```

Expected: Compose renders valid YAML with `api`, `bot`, `worker`, and `postgres`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml docker-compose.local.yml
git commit -m "chore: configure durable server compose stack"
```

---

### Task 11: Server Beta Runbook

**Files:**
- Create: `docs/deployment/server-beta.md`

- [ ] **Step 1: Create deployment runbook**

Create `docs/deployment/server-beta.md`:

```markdown
# Server Beta Deployment

## Purpose

This runbook starts the closed beta backend with a Telegram bot, FastAPI health endpoint, durable worker, PostgreSQL, and persistent local object storage.

## First Setup

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Fill these values in `.env`:

   ```dotenv
   TELEGRAM_BOT_TOKEN=replace-with-beta-bot-token
   DEEPSEEK_API_KEY=replace-with-deepseek-key
   POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator
   JOB_STORE_BACKEND=postgres
   TRANSLATION_EXECUTION_MODE=worker
   OBJECT_STORAGE_ROOT=/data/object-storage
   ```

3. Start the stack in detached mode:

   ```bash
   docker compose up -d --build
   ```

4. Check health:

   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/ready
   ```

## Daily Operation

Show running services:

```bash
docker compose ps
```

Watch bot logs:

```bash
docker compose logs -f bot
```

Watch worker logs:

```bash
docker compose logs -f worker
```

Restart one service:

```bash
docker compose restart worker
```

Stop everything:

```bash
docker compose down
```

## Crash And Resume Behavior

- If the Telegram bot stops, queued and running jobs remain in PostgreSQL.
- If the worker stops during a fragment, completed fragments remain saved and the active fragment becomes claimable again after the lease expires.
- If the server restarts, Docker starts services again through `restart: unless-stopped`.
- Users can resume interrupted jobs from the bot because ownership, job status, work units, and output object keys are persisted.

## Backup

Back up PostgreSQL:

```bash
docker compose exec postgres pg_dump -U translator translator > translator-backup.sql
```

Back up object storage:

```bash
docker run --rm -v new-project-2_object-storage:/data/object-storage -v "$PWD":/backup alpine tar czf /backup/object-storage-backup.tgz /data/object-storage
```

## Restore

Restore PostgreSQL:

```bash
docker compose exec -T postgres psql -U translator translator < translator-backup.sql
```

Restore object storage:

```bash
docker run --rm -v new-project-2_object-storage:/data/object-storage -v "$PWD":/backup alpine tar xzf /backup/object-storage-backup.tgz -C /
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment/server-beta.md
git commit -m "docs: add server beta deployment runbook"
```

---

### Task 12: Verification Gate

**Files:**
- No code files unless earlier tasks fail verification.

- [ ] **Step 1: Run unit tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass. PostgreSQL integration tests skip unless `TEST_POSTGRES_DSN` is set.

- [ ] **Step 2: Run compile check**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache PYTHONPATH=src python3 -m compileall src
```

Expected: all files compile.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Run Compose config check**

Run:

```bash
docker compose config
```

Expected: valid Compose output.

- [ ] **Step 5: Optional local server smoke test with Docker**

Run:

```bash
cp .env.example .env
docker compose up -d --build postgres api
curl http://localhost:8000/health
curl http://localhost:8000/ready
docker compose down
```

Expected:

```json
{"service":"FolioLoom","status":"ok"}
```

and readiness returns `status=ready`.

- [ ] **Step 6: Final commit**

```bash
git status --short
git add .
git commit -m "feat: prepare durable backend beta"
```

---

## Acceptance Criteria

- A server beta can run with `docker compose up -d --build`.
- PostgreSQL stores jobs and work units for server mode.
- Object storage is mounted as a durable Docker volume.
- The Telegram bot does not perform paid translation inline when `TRANSLATION_EXECUTION_MODE=worker`.
- Worker process claims queued work units, translates them, persists each result, and can continue after restart.
- Stale translating units are reclaimed after their lease expires.
- A user can resume an interrupted job without reuploading the file or paying again in the beta flow.
- `/health` remains lightweight and `/ready` verifies object storage plus job store access.
- Unit tests pass, compile check passes, and Compose config validates.

## Explicit Non-Scope

- Real payment provider integration.
- Translation quality profile changes.
- New document formats.
- WhatsApp or social network channels.
- S3/R2 object storage migration.
- Admin web dashboard.
- Antivirus and parser sandbox rollout.

These items remain in the product specification, but the closed beta backend should become durable before they are expanded.
