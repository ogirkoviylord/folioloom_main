# Durable Backend Beta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare FolioLoom for a closed server beta where bot/worker crashes, Ctrl+C, SSH disconnects, and restarts do not lose translation progress.

**Architecture:** Move beta execution to durable backend mode: Telegram creates and displays jobs, a worker process translates persisted work units, PostgreSQL or SQLite stores job/work-unit state, and object storage stores originals/intermediates/results. Translation quality, prompts, language profiles, and format behavior are out of scope for this plan unless a backend change would otherwise lose progress.

**Tech Stack:** Python 3.13, aiogram, FastAPI, Docker Compose, PostgreSQL scheduler backend, SQLite dev backend, local object storage volume, existing `unittest` suite.

---

## Scope

This plan prepares a server beta, not a full paid production launch.

Included:

- Server execution mode that queues work instead of translating inside the Telegram handler.
- Durable pending/running/completed state across bot restart, worker restart, and server restart.
- Visible `My Books`/resume path for unfinished jobs.
- Worker process that can pick up persisted work after restart.
- Docker Compose beta stack with persistent Postgres and object-storage volumes.
- Health/readiness checks and operator runbook.
- Beta-safe logging and required-secret validation.

Excluded:

- Payment provider integration.
- Translation prompt/profile improvements.
- New document formats.
- WhatsApp/web channels.
- Cover thumbnails and polished book-card UI unless already needed by resume/history.

---

## File Structure

- Modify `src/translator_service/config.py`: add beta execution mode and server-readiness settings.
- Modify `src/translator_service/bot_translation_service.py`: add queue-only confirmation, persisted status/result helpers, and resume-safe job state transitions.
- Modify `src/translator_service/bot/runtime.py`: make `/confirm`, progress, status, cancel, and `My Books` use durable backend mode when enabled.
- Modify `src/translator_service/api.py`: add readiness endpoint for server beta.
- Modify `src/translator_service/worker.py`: make worker startup validate backend/storage configuration and log lifecycle events.
- Modify `docker-compose.yml` or create `docker-compose.beta.yml`: server beta stack.
- Create or modify `.env.server.example`: beta env contract.
- Create `docs/deployment/server-beta-runbook.md`: deployment, logs, restart, backup, restore, and rollback instructions.
- Modify tests:
  - `tests/test_config.py`
  - `tests/test_bot_translation_service.py`
  - `tests/test_bot_runtime.py`
  - `tests/test_api.py`
  - `tests/test_worker.py`

---

### Task 1: Server Execution Mode Configuration

**Files:**
- Modify: `src/translator_service/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Add:

```python
def test_settings_default_to_inline_execution_mode(self):
    settings = Settings()

    self.assertEqual(settings.translation_execution_mode, "inline")


def test_settings_read_worker_execution_mode_from_environment(self):
    with patched_env(TRANSLATION_EXECUTION_MODE="worker"):
        settings = Settings()

    self.assertEqual(settings.translation_execution_mode, "worker")


def test_settings_reject_unknown_execution_mode(self):
    with patched_env(TRANSLATION_EXECUTION_MODE="banana"):
        with self.assertRaises(ValueError):
            Settings()
```

If `tests/test_config.py` already has an env patch helper, reuse it. If not, add:

```python
from contextlib import contextmanager
import os


@contextmanager
def patched_env(**values):
    original = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
```

- [ ] **Step 2: Run config tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_config
```

Expected: fail because `translation_execution_mode` does not exist.

- [ ] **Step 3: Implement config field**

Add to `Settings`:

```python
translation_execution_mode: str = field(
    default_factory=lambda: _validated_choice(
        os.getenv("TRANSLATION_EXECUTION_MODE", "inline"),
        allowed={"inline", "worker"},
        name="TRANSLATION_EXECUTION_MODE",
    )
)
```

Add helper:

```python
def _validated_choice(value: str, *, allowed: set[str], name: str) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return normalized
```

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_config
```

Expected: config tests pass.

---

### Task 2: Queue-Only Confirmation Service Path

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Test: `tests/test_bot_translation_service.py`

- [ ] **Step 1: Write failing service test for queue-only confirmation**

Add:

```python
def test_queue_pending_translation_creates_persistent_job_without_translating(self):
    with TemporaryDirectory() as temp_dir:
        storage = LocalObjectStorage(Path(temp_dir) / "objects")
        store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
        self.addCleanup(store.close)
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
            file_storage=storage,
            persistent_job_store=store,
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.",
            source_language="en",
        )
        service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

        queued = service.queue_pending_translation(user_telegram_id=42)

        self.assertEqual(queued.status, "queued")
        self.assertEqual(queued.file_name, "notes.txt")
        self.assertFalse(queued.has_result)
        self.assertEqual(len(store.list_work_units(queued.job_id)), 2)
```

- [ ] **Step 2: Run service test to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service.BotTranslationServiceTest.test_queue_pending_translation_creates_persistent_job_without_translating
```

Expected: fail because `queue_pending_translation` does not exist.

- [ ] **Step 3: Implement queue-only method**

Add a method that reuses current persistent planning but does not run translator:

```python
def queue_pending_translation(self, *, user_telegram_id: int) -> UserBookSummary:
    with self._state_lock:
        pending = self._pending.pop(user_telegram_id, None)
        if pending is None:
            raise ValueError("No pending translation for this user")

    upload = validate_document_upload(
        file_name=pending.file_name,
        size_bytes=len(pending.content),
        max_upload_mb=self._max_upload_mb,
    )
    document_kind = _document_kind_from_format(upload.document_format)
    if document_kind is None:
        raise ValueError("Only TXT, DOCX, and EPUB queueing is supported")
    if (
        self._file_storage is None
        or self._persistent_job_store is None
        or pending.source_object_key is None
    ):
        raise ValueError("Durable queue mode requires object storage and persistent jobs")

    plan = _create_persistent_job_plan(
        document_kind=document_kind,
        store=self._persistent_job_store,
        storage=self._file_storage,
        pending=pending,
        max_fragment_chars=self._max_fragment_chars,
    )
    return self._book_summary_from_job(plan.job)
```

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service.BotTranslationServiceTest.test_queue_pending_translation_creates_persistent_job_without_translating
```

Expected: targeted test passes.

---

### Task 3: Runtime Worker Mode Confirmation

**Files:**
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Write failing runtime helper test**

Keep this unit-level so it does not require Telegram network:

```python
def test_runtime_config_exposes_worker_execution_mode(self):
    config = BotRuntimeConfig(translation_execution_mode="worker")

    self.assertEqual(config.translation_execution_mode, "worker")
```

Add a pure helper test:

```python
def test_should_queue_translation_when_worker_mode_enabled(self):
    self.assertTrue(_should_queue_translation(BotRuntimeConfig(translation_execution_mode="worker")))
    self.assertFalse(_should_queue_translation(BotRuntimeConfig(translation_execution_mode="inline")))
```

- [ ] **Step 2: Run runtime tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime
```

Expected: fail because config field/helper does not exist.

- [ ] **Step 3: Implement runtime config and helper**

Add to `BotRuntimeConfig`:

```python
translation_execution_mode: str = "inline"
```

Add helper:

```python
def _should_queue_translation(config: BotRuntimeConfig) -> bool:
    return config.translation_execution_mode == "worker"
```

Update `build_translation_service` only if needed to pass `use_scheduler_runner` separately from queue mode. Do not make the Telegram handler run work in worker mode.

- [ ] **Step 4: Change confirm path**

Inside `_confirm_pending_translation`, branch before calling the blocking translation execution:

```python
if _should_queue_translation(config):
    queued = service.queue_pending_translation(user_telegram_id=message.from_user.id)
    await message.answer(
        build_user_book_queued_message(queued, service.get_interface_language(message.from_user.id)),
        reply_markup=_menu_detail_keyboard(service.get_interface_language(message.from_user.id)),
    )
    return
```

If `_confirm_pending_translation` currently does not receive `config`, update its signature and call sites.

- [ ] **Step 5: Verify runtime tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime
```

Expected: runtime tests pass.

---

### Task 4: Worker Resume After Crash Contract

**Files:**
- Modify: `src/translator_service/worker.py`
- Modify: `src/translator_service/persistent_jobs.py` if expired leases are not already fully covered.
- Test: `tests/test_worker.py`
- Test: `tests/test_persistent_jobs.py`

- [ ] **Step 1: Write failing crash-resume test**

Add a test that simulates a claimed work unit whose worker died before completion:

```python
def test_expired_translating_unit_can_be_claimed_after_worker_crash(self):
    store = SQLiteTranslationJobStore(":memory:")
    self.addCleanup(store.close)
    job = _create_job_with_two_units(store)
    first_claim = store.claim_next_work_unit(
        worker_id="worker-a",
        lease_seconds=1,
        limits=SchedulerLimits(),
    )

    store.force_expire_work_unit_lease(first_claim.work_unit_id)

    second_claim = store.claim_next_work_unit(
        worker_id="worker-b",
        lease_seconds=60,
        limits=SchedulerLimits(),
    )

    self.assertEqual(second_claim.work_unit_id, first_claim.work_unit_id)
    self.assertEqual(second_claim.worker_id, "worker-b")
```

If test-only lease forcing is undesirable, create the first claim with `lease_seconds=1`, sleep just over one second, and keep the test marked as slow only if the suite already supports slow tests. Prefer a deterministic helper scoped to tests if existing patterns allow it.

- [ ] **Step 2: Run tests to verify red or confirm existing support**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs tests.test_worker
```

Expected: the new test fails if expired-lease reclaim is incomplete. If it already passes with existing methods, keep the test as regression coverage and continue.

- [ ] **Step 3: Implement or tighten expired-lease reclaim**

The claim query must treat `translating` units with expired `lease_until` as claimable. Completion must still require the matching `claim_token`.

Ensure stale worker completion is ignored:

```python
completed = store.complete_claimed_work_unit(
    work_unit_id=claim.work_unit_id,
    claim_token="old-token",
    translated_text="late result",
    prompt_tokens=1,
    completion_tokens=1,
    cache_hit_tokens=0,
    cache_miss_tokens=1,
)
self.assertIsNone(completed)
```

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs tests.test_worker
```

Expected: tests pass.

---

### Task 5: User Resume and Partial Result From History

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Modify: `src/translator_service/bot/runtime.py`
- Modify: `src/translator_service/bot/messages.py`
- Test: `tests/test_bot_translation_service.py`
- Test: `tests/test_bot_runtime.py`
- Test: `tests/test_bot_messages.py`

- [ ] **Step 1: Add service test for resume action**

Add:

```python
def test_resume_user_book_requeues_cancelled_job_without_losing_completed_units(self):
    cancelled_summary = service.resume_user_book(user_telegram_id=42, job_id=job.id)

    self.assertEqual(cancelled_summary.status, "queued")
    translated_units = [
        unit for unit in store.list_work_units(job.id)
        if unit.status.value in {"translated", "cached"}
    ]
    self.assertEqual(len(translated_units), 1)
```

Use existing cancellation/resume fixtures in `tests/test_bot_translation_service.py`.

- [ ] **Step 2: Add message tests**

Add:

```python
def test_book_detail_message_shows_continue_when_resumable(self):
    message = build_user_book_detail_message(
        {
            "file_name": "book.epub",
            "status": "cancelled",
            "can_resume": True,
            "has_partial_result": True,
            "has_result": True,
            "target_language": "uk",
            "source_language": "en",
        },
        "en",
    )

    self.assertIn("cancelled", message.lower())
    self.assertIn("partial", message.lower())
```

- [ ] **Step 3: Add runtime keyboard test**

Add:

```python
def test_book_detail_keyboard_shows_continue_for_resumable_job(self):
    keyboard = _book_detail_keyboard(
        {"job_id": "job-1", "has_result": True, "can_resume": True},
        page=0,
        interface_language="en",
    )

    self.assertIn(
        ("Continue Translation", "resume_book:job-1"),
        [(button.text, button.callback_data) for row in keyboard.inline_keyboard for button in row],
    )
```

- [ ] **Step 4: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service tests.test_bot_messages tests.test_bot_runtime
```

Expected: failures around missing/unfinished resume UI pieces.

- [ ] **Step 5: Implement resume callbacks**

Add callback:

```python
@router.callback_query(F.data.startswith("resume_book:"))
async def resume_book(callback: CallbackQuery) -> None:
    interface_language = service.get_interface_language(callback.from_user.id)
    job_id = (callback.data or "").split(":", 1)[1]
    summary = service.resume_user_book(user_telegram_id=callback.from_user.id, job_id=job_id)
    if summary is None:
        await callback.answer(build_download_unavailable_message(interface_language), show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            build_user_book_detail_message(summary, interface_language=interface_language),
            reply_markup=_book_detail_keyboard(summary, page=0, interface_language=interface_language),
        )
```

In worker mode, this should only mark the job resumable/queued. The worker process performs the actual translation.

- [ ] **Step 6: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service tests.test_bot_messages tests.test_bot_runtime
```

Expected: tests pass.

---

### Task 6: Server Beta Compose and Environment

**Files:**
- Create: `docker-compose.beta.yml`
- Create: `.env.server.example`
- Modify: `README.md`

- [ ] **Step 1: Add `docker-compose.beta.yml`**

Create:

```yaml
services:
  api:
    build: .
    command: uvicorn translator_service.api:create_app --factory --host 0.0.0.0 --port 8000
    env_file: .env.server
    ports:
      - "8000:8000"
    volumes:
      - object-storage:/app/var/object-storage
    depends_on:
      - postgres
    restart: unless-stopped

  bot:
    build: .
    command: python -m translator_service.bot
    env_file: .env.server
    volumes:
      - object-storage:/app/var/object-storage
    depends_on:
      - postgres
    restart: unless-stopped

  worker:
    build: .
    command: python -m translator_service.worker
    env_file: .env.server
    volumes:
      - object-storage:/app/var/object-storage
    depends_on:
      - postgres
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: translator
      POSTGRES_USER: translator
      POSTGRES_PASSWORD: translator
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres-data:
  object-storage:
```

- [ ] **Step 2: Add `.env.server.example`**

Create:

```text
ENVIRONMENT=beta
SERVICE_NAME=FolioLoom Beta
MAX_UPLOAD_MB=50
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
DEEPSEEK_API_KEYS=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
TRANSLATION_EXECUTION_MODE=worker
SCHEDULER_BACKEND=postgres
POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator
OBJECT_STORAGE_ROOT=var/object-storage
PERSISTENT_JOBS_DB_PATH=var/jobs.sqlite3
USER_SETTINGS_DB_PATH=var/user-settings.sqlite3
TRANSLATION_RUN_LOG_ROOT=var/translation-runs
SECURITY_MAX_EVENTS_PER_RUN=20
SECURITY_MAX_UNSAFE_MODEL_OUTPUTS_PER_RUN=3
SECURITY_MAX_REPAIR_FAILURES_PER_RUN=1
```

- [ ] **Step 3: Update README server section**

Add commands:

```bash
cp .env.server.example .env.server
docker compose -f docker-compose.beta.yml up -d --build
docker compose -f docker-compose.beta.yml logs -f bot
docker compose -f docker-compose.beta.yml logs -f worker
docker compose -f docker-compose.beta.yml down
```

- [ ] **Step 4: Validate compose config**

Run:

```bash
docker compose -f docker-compose.beta.yml config
```

Expected: compose prints a resolved config without errors.

If Docker is not available locally, record that validation must be run on the server before beta.

---

### Task 7: API Readiness and Required Secret Checks

**Files:**
- Modify: `src/translator_service/api.py`
- Modify: `src/translator_service/config.py`
- Test: `tests/test_api.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add readiness tests**

Add:

```python
def test_readiness_payload_reports_missing_secrets(self):
    settings = Settings()
    payload = readiness_payload(settings, check_storage=False, check_database=False)

    self.assertIn("telegram_bot_token", payload["missing"])
    self.assertIn("deepseek_api_key", payload["missing"])
```

- [ ] **Step 2: Run API tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_api
```

Expected: fail because readiness helper does not exist.

- [ ] **Step 3: Implement readiness payload**

Add:

```python
def readiness_payload(
    settings: Settings | None = None,
    *,
    check_storage: bool = True,
    check_database: bool = True,
) -> dict:
    active_settings = settings or Settings()
    missing = []
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        missing.append("telegram_bot_token")
    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEYS")):
        missing.append("deepseek_api_key")
    return {
        "service": active_settings.service_name,
        "status": "ok" if not missing else "degraded",
        "execution_mode": active_settings.translation_execution_mode,
        "scheduler_backend": active_settings.scheduler_backend,
        "missing": missing,
    }
```

Expose:

```python
@app.get("/ready")
def ready() -> dict:
    return readiness_payload(active_settings)
```

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_api
```

Expected: API tests pass.

---

### Task 8: Server Beta Runbook

**Files:**
- Create: `docs/deployment/server-beta-runbook.md`

- [ ] **Step 1: Create runbook**

Create:

```markdown
# FolioLoom Server Beta Runbook

## First Deploy

1. Install Docker and Docker Compose plugin.
2. Clone the repository.
3. Copy `.env.server.example` to `.env.server`.
4. Fill `TELEGRAM_BOT_TOKEN` and one DeepSeek key field.
5. Run `docker compose -f docker-compose.beta.yml up -d --build`.
6. Check `curl http://localhost:8000/health`.
7. Check `curl http://localhost:8000/ready`.
8. Open Telegram and send `/start` to the beta bot.

## Logs

```bash
docker compose -f docker-compose.beta.yml logs -f bot
docker compose -f docker-compose.beta.yml logs -f worker
docker compose -f docker-compose.beta.yml logs -f api
```

## Restart

```bash
docker compose -f docker-compose.beta.yml restart bot
docker compose -f docker-compose.beta.yml restart worker
```

## Backup

```bash
docker compose -f docker-compose.beta.yml exec postgres pg_dump -U translator translator > folioloom-beta.sql
docker run --rm -v folioloom_object-storage:/data -v "$PWD":/backup alpine tar czf /backup/object-storage.tar.gz /data
```

## Restore

```bash
cat folioloom-beta.sql | docker compose -f docker-compose.beta.yml exec -T postgres psql -U translator translator
docker run --rm -v folioloom_object-storage:/data -v "$PWD":/backup alpine sh -c "cd / && tar xzf /backup/object-storage.tar.gz"
```

## Crash Recovery Check

1. Start a translation.
2. Stop the worker with `docker compose -f docker-compose.beta.yml stop worker`.
3. Start it again with `docker compose -f docker-compose.beta.yml start worker`.
4. Confirm the translation continues from persisted work units.
5. Restart the bot and confirm `My Books` still shows the job.
```

- [ ] **Step 2: Review commands against compose project name**

If the compose project name differs, document the exact volume names produced by:

```bash
docker volume ls | grep folioloom
```

---

### Task 9: Full Verification

**Files:**
- All files touched by the plan.

- [ ] **Step 1: Run tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Compile**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache PYTHONPATH=src python3 -m compileall src
```

Expected: compile completes without errors.

- [ ] **Step 3: Diff check**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 4: Compose config check**

Run:

```bash
docker compose -f docker-compose.beta.yml config
```

Expected: resolved compose config prints without errors.

- [ ] **Step 5: Commit**

Run:

```bash
git add .env.server.example docker-compose.beta.yml docs/deployment/server-beta-runbook.md src/translator_service/config.py src/translator_service/api.py src/translator_service/bot_translation_service.py src/translator_service/bot/runtime.py src/translator_service/bot/messages.py src/translator_service/worker.py tests/test_config.py tests/test_api.py tests/test_bot_translation_service.py tests/test_bot_runtime.py tests/test_bot_messages.py tests/test_worker.py
git commit -m "feat: prepare durable backend beta"
```

---

## Self-Review

- Spec coverage: covers server beta execution, durable queue mode, worker split, crash/restart progress preservation, resume UI, compose deployment, readiness, backups, and operator runbook.
- Scope control: translation quality, prompts, language profiles, and new formats are explicitly excluded.
- Type consistency: `translation_execution_mode` uses `inline` and `worker`; queued jobs are represented through existing `UserBookSummary`; worker mode does not require Telegram to execute translation.
