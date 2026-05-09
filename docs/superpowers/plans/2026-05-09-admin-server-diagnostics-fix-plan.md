# Admin Server Diagnostics Fix Implementation Plan


**Goal:** Make the deployed admin console reflect the real bot state after deploy: env-backed integrations, AI keys, live translations, logs, users, operations, and backups must all point at the same runtime data.

**Architecture:** Keep the current central admin console, but add explicit read models for bootstrap env configuration and shared runtime state. The server runtime should have one shared `/data` filesystem mount across `api`, `bot`, and `worker`; admin pages should read runtime state after auth; logs and operations should link to specific run details.

**Tech Stack:** Python 3.13, FastAPI, SQLite, Postgres scheduler store, Docker Compose, unittest, ruff.

---

## File Map

- `docker-compose.yml`: shared runtime mounts for `api`, `bot`, `worker`.
- `.env.server.example`: production runtime paths.
- `scripts/server_smoke_check.sh`: cross-container runtime smoke checks.
- `scripts/backup_server_data.py`: backup runtime path mapping and full runtime archive.
- `src/translator_service/admin/bootstrap_config.py`: new env-backed admin read model.
- `src/translator_service/admin/routes.py`: wire bootstrap config, defer expensive reads until after auth, improve operation/log routing.
- `src/translator_service/admin/views.py`: show env-backed secrets as masked configured fallback, not missing.
- `src/translator_service/admin/live.py`: count active persistent jobs.
- `src/translator_service/admin/operations.py`: include cancelled/expired jobs and link to concrete run details.
- `src/translator_service/user_activity.py`: inclusive date filtering.
- `src/translator_service/bot/runtime.py`: resolve scheduler backend mismatch or fail deployment clearly.
- `src/translator_service/admin/deployment_smoke.py`: validate bot/worker scheduler store compatibility.
- `docs/deployment/admin-vps-runbook.md`: updated deploy, rescue, and verification steps.
- `docs/deployment/restore-runbook.md`: updated restore model.
- `README.md`: concise runtime mount note.
- Tests: `tests/test_admin_routes.py`, `tests/test_admin_live_monitor.py`, `tests/test_admin_operations.py`, `tests/test_user_activity.py`, `tests/test_backup_server_data.py`, `tests/test_server_deployment_config.py`, `tests/test_admin_deployment_smoke.py`, `tests/test_bot_runtime.py`.

---

### Task 1: Lock The Server Runtime Filesystem

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.server.example`
- Modify: `scripts/server_smoke_check.sh`
- Modify: `tests/test_server_deployment_config.py`
- Modify: `docs/deployment/admin-vps-runbook.md`
- Modify: `README.md`

- [ ] **Step 1: Keep the existing failing/passing regression tests**

Run:

```bash
python3 -m unittest tests.test_server_deployment_config
```

Expected: tests assert `./var:/data` exists for `api`, `bot`, and `worker`, and production env paths use `/data/...`.

- [ ] **Step 2: Verify compose model**

Run:

```bash
docker compose --env-file .env.server.example config --quiet
```

Expected: exit code `0`.

- [ ] **Step 3: Ensure smoke check covers all runtime services**

`scripts/server_smoke_check.sh` must include these commands:

```sh
docker compose exec -T api python -m translator_service.admin.deployment_smoke
docker compose exec -T bot python -m translator_service.admin.deployment_smoke $admin_smoke_args
docker compose exec -T worker python -m translator_service.admin.deployment_smoke $admin_smoke_args
```

- [ ] **Step 4: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_server_deployment_config
ruff check tests/test_server_deployment_config.py
```

Expected: all pass.

---

### Task 2: Back Up The Whole Runtime Tree

**Files:**
- Modify: `scripts/backup_server_data.py`
- Modify: `tests/test_backup_server_data.py`
- Modify: `docs/deployment/restore-runbook.md`
- Modify: `docs/deployment/admin-vps-runbook.md`

- [ ] **Step 1: Write tests for `/data` host mapping and full runtime archive**

Add tests proving:

```python
self.assertEqual(
    backup_server_data.host_runtime_path(Path("/data/run-logs")),
    Path("var/run-logs"),
)
self.assertEqual(
    backup_server_data.host_runtime_path(Path("/data/runtime/user-settings.sqlite3")),
    Path("var/runtime/user-settings.sqlite3"),
)
```

Add an archive test where `var/run-logs/run-1/run.json`, `var/runtime/admin.sqlite3`, `var/runtime/user-settings.sqlite3`, and `var/object-storage/book.txt` all appear in the generated tarball.

- [ ] **Step 2: Run tests and see current gap**

Run:

```bash
python3 -m unittest tests.test_backup_server_data
```

Expected before implementation: new full-runtime archive test fails because run logs/user settings are not archived.

- [ ] **Step 3: Implement host runtime mapping and archive root**

Update `run_backup()` so paths from env are mapped through `host_runtime_path()`, then archive the common host runtime root `var/` instead of only object storage plus admin DB.

Core behavior:

```python
runtime_root = host_runtime_path(Path(os.getenv("FOLIOLOOM_RUNTIME_ROOT", "/data")))
if runtime_root == Path("var"):
    archive.add(runtime_root, arcname="var")
```

Keep manifest fields for `object_storage_root` and `admin_db_path`, and add `runtime_root`.

- [ ] **Step 4: Strengthen backup validation**

If database row counts show jobs but archived runtime file count is zero, raise:

```python
RuntimeError("database contains jobs but runtime archive has no files")
```

- [ ] **Step 5: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_backup_server_data
ruff check scripts/backup_server_data.py tests/test_backup_server_data.py
```

Expected: all pass.

---

### Task 3: Show Env-Backed Telegram And DeepSeek In Admin

**Files:**
- Create: `src/translator_service/admin/bootstrap_config.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Modify: `src/translator_service/admin/action_center.py`
- Modify: `src/translator_service/admin/secret_safety.py`
- Test: `tests/test_admin_routes.py`
- Test: `tests/test_admin_action_center.py`
- Test: `tests/test_admin_secret_safety.py`

- [ ] **Step 1: Write failing route tests**

Add tests with `patch.dict("os.environ", {"DEEPSEEK_API_KEYS": "key-a,key-b", "TELEGRAM_BOT_TOKEN": "123:abc"})` and an empty admin store.

Assert:

```python
self.assertIn("env fallback", response.text)
self.assertIn("2 env keys", response.text)
self.assertIn("Telegram", response.text)
self.assertNotIn("DeepSeek keys missing", overview.text)
```

- [ ] **Step 2: Create bootstrap config read model**

Create `src/translator_service/admin/bootstrap_config.py` with:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapSecretSummary:
    owner_id: str
    label: str
    source: str
    configured: bool
    count: int = 0
    masked_value: str = "configured in env"


def deepseek_env_key_count() -> int:
    raw_keys = os.getenv("DEEPSEEK_API_KEYS", "")
    if raw_keys.strip():
        return len({key.strip() for key in raw_keys.split(",") if key.strip()})
    return 1 if os.getenv("DEEPSEEK_API_KEY", "").strip() else 0


def telegram_env_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())


def bootstrap_secret_summaries() -> tuple[BootstrapSecretSummary, ...]:
    deepseek_count = deepseek_env_key_count()
    return (
        BootstrapSecretSummary(
            owner_id="deepseek",
            label="DeepSeek API keys",
            source="env fallback",
            configured=deepseek_count > 0,
            count=deepseek_count,
            masked_value=f"{deepseek_count} env keys" if deepseek_count else "missing",
        ),
        BootstrapSecretSummary(
            owner_id="telegram",
            label="Telegram bot token",
            source="env fallback",
            configured=telegram_env_configured(),
            count=1 if telegram_env_configured() else 0,
        ),
    )
```

- [ ] **Step 3: Wire bootstrap summaries into admin pages**

In `routes.py`, pass `bootstrap_secret_summaries()` into `integrations_body()`, `ai_providers_body()`, `build_action_center()`, and `build_secret_safety_report()`.

- [ ] **Step 4: Render without exposing secrets**

In `views.py`, show env rows as:

```html
<span class="status">env fallback</span>
<code>configured in env</code>
```

Never render raw `TELEGRAM_BOT_TOKEN`, `DEEPSEEK_API_KEY`, or `DEEPSEEK_API_KEYS`.

- [ ] **Step 5: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_admin_routes tests.test_admin_action_center tests.test_admin_secret_safety
ruff check src/translator_service/admin tests/test_admin_routes.py tests/test_admin_action_center.py tests/test_admin_secret_safety.py
```

Expected: all pass.

---

### Task 4: Fix Live Monitor Counts

**Files:**
- Modify: `src/translator_service/admin/live.py`
- Test: `tests/test_admin_live_monitor.py`

- [ ] **Step 1: Write failing test**

Create an `OperationsOverview` with one running job and no run logs.

Expected:

```python
self.assertEqual(snapshot.active_translations, 1)
```

- [ ] **Step 2: Implement operations-aware active count**

In `build_live_monitor_snapshot()`, compute:

```python
active_from_runs = sum(1 for run in runs if run.status in _ACTIVE_STATUSES)
active_from_operations = (
    operations.job_counts_by_state.get("running", 0) if operations is not None else 0
)
active_translations = max(active_from_runs, active_from_operations)
```

- [ ] **Step 3: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_admin_live_monitor tests.test_admin_routes
```

Expected: all pass.

---

### Task 5: Link Operations To Concrete Translation Logs

**Files:**
- Modify: `src/translator_service/admin/operations.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_operations.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing test**

Create a run summary where `summary.job_id == "job-ready"` and `Path(summary.run_dir).name == "run-123"`.

Expected:

```python
self.assertEqual(by_id["job-ready"].log_href, "/admin/logs/run-123")
self.assertIn('href="/admin/logs/run-123"', html)
```

- [ ] **Step 2: Build concrete href map**

Replace:

```python
job_log_hrefs={job_id: "/admin/logs" for job_id in job_ids_with_logs}
```

with:

```python
job_log_hrefs={
    summary.job_id: f"/admin/logs/{Path(summary.run_dir).name}"
    for summary in list_translation_run_summaries(log_root, limit=1000)
    if summary.job_id
}
```

- [ ] **Step 3: Keep URL safety**

Allow `/admin/logs/{run_id}` in `_safe_operation_log_href()` and keep external URLs falling back to `/admin/logs`.

- [ ] **Step 4: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_admin_operations tests.test_admin_routes
```

Expected: all pass.

---

### Task 6: Include Cancelled And Expired Jobs In Operations

**Files:**
- Modify: `src/translator_service/admin/operations.py`
- Test: `tests/test_admin_operations.py`

- [ ] **Step 1: Write failing test**

Create persistent jobs with statuses:

```python
PersistentTranslationJobStatus.CANCELLED
PersistentTranslationJobStatus.EXPIRED
```

Expected: both appear in `build_persistent_operations_overview(...).jobs`.

- [ ] **Step 2: Add statuses**

Extend `_PERSISTENT_OPERATION_STATUSES`:

```python
PersistentTranslationJobStatus.CANCELLED,
PersistentTranslationJobStatus.EXPIRED,
```

- [ ] **Step 3: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_admin_operations
```

Expected: all pass.

---

### Task 7: Make Old Logs Reachable

**Files:**
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Modify: `src/translator_service/admin/translation_logs.py`
- Test: `tests/test_admin_translation_logs.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing test for larger limit**

Create 125 run dirs and assert `/admin/logs` can show or page beyond the first 100.

Minimum acceptable behavior:

```python
response = client.get("/admin/logs?limit=200")
self.assertIn("run-124", response.text)
```

- [ ] **Step 2: Add safe `limit` query param**

In logs route, parse:

```python
limit = max(1, min(int(request.query_params.get("limit", "100")), 500))
```

Pass `limit=limit` to `list_translation_run_summaries()`.

- [ ] **Step 3: Add UI control**

In `logs_body()`, include a compact select or input for `limit` with values `100`, `200`, `500`.

- [ ] **Step 4: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_admin_translation_logs tests.test_admin_routes
```

Expected: all pass.

---

### Task 8: Fix Activity Date Filtering

**Files:**
- Modify: `src/translator_service/user_activity.py`
- Test: `tests/test_user_activity.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing test**

Insert an event with `created_at` on `2026-05-09T12:00:00+00:00`, then query with `date_to="2026-05-09"`.

Expected:

```python
self.assertEqual(len(events), 1)
```

- [ ] **Step 2: Normalize date-only `date_to`**

In `SQLiteUserActivityStore.list_events()`, if `date_to` has length `10`, compare with end of day:

```python
if date_to and len(date_to) == 10:
    params.append(f"{date_to}T23:59:59.999999+00:00")
else:
    params.append(date_to)
```

- [ ] **Step 3: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_user_activity tests.test_admin_routes
```

Expected: all pass.

---

### Task 9: Resolve Scheduler Backend Mismatch

**Files:**
- Modify: `src/translator_service/bot/runtime.py`
- Modify: `src/translator_service/admin/deployment_smoke.py`
- Test: `tests/test_bot_runtime.py`
- Test: `tests/test_admin_deployment_smoke.py`

- [ ] **Step 1: Decide MVP rule**

For this deployment slice, use a conservative rule:

```text
If SCHEDULER_BACKEND=postgres, bot runtime must not silently create SQLite jobs for worker-owned processing.
```

Until `BotTranslationService` can accept the Postgres scheduler store cleanly, deployment smoke should fail with a clear message if production is configured as Postgres but bot still uses SQLite job creation.

- [ ] **Step 2: Add failing deployment smoke test**

With:

```python
Settings(
    scheduler_backend="postgres",
    persistent_jobs_db_path="/data/runtime/jobs.sqlite3",
    postgres_dsn="postgresql://translator:secret@postgres:5432/translator",
    ...
)
```

Expected:

```python
with self.assertRaisesRegex(AdminDeploymentCheckError, "Bot scheduler backend mismatch"):
    check_admin_runtime_configuration(settings)
```

- [ ] **Step 3: Implement explicit mismatch check**

In `deployment_smoke.py`, add:

```python
if settings.scheduler_backend == "postgres":
    raise AdminDeploymentCheckError(
        "Bot scheduler backend mismatch: bot currently creates SQLite persistent jobs; "
        "set SCHEDULER_BACKEND=sqlite for this deployment or implement bot Postgres store wiring."
    )
```

If we choose to fully wire Postgres instead, replace this step with adapting `build_translation_service()` to accept `open_scheduler_store(settings)` and update types away from `SQLiteTranslationJobStore` assumptions.

- [ ] **Step 4: Update server env/docs if staying SQLite for MVP**

If we choose the conservative MVP rule, change `.env.server.example`:

```env
SCHEDULER_BACKEND=sqlite
```

and document that Postgres remains prepared but not active for bot jobs until the next backend slice.

- [ ] **Step 5: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_bot_runtime tests.test_admin_deployment_smoke tests.test_worker
```

Expected: all pass.

---

### Task 10: Defer Admin Data Reads Until After Auth

**Files:**
- Modify: `src/translator_service/admin/routes.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing test**

Patch a heavy read function like `_live_snapshot` and request `/admin/live` without a session.

Expected:

```python
snapshot.assert_not_called()
self.assertEqual(response.status_code, 303)
```

- [ ] **Step 2: Use callable body consistently**

Change routes like:

```python
body=live_body(_live_snapshot(settings), ...)
```

to:

```python
body=lambda session: live_body(_live_snapshot(settings), ...)
```

Apply the same pattern to `/logs`, `/activity`, `/users`, and `/security/events`.

- [ ] **Step 3: Run focused checks**

Run:

```bash
python3 -m unittest tests.test_admin_routes
```

Expected: all pass.

---

## Final Verification

- [ ] Run all tests:

```bash
python3 -m unittest discover tests
```

- [ ] Run predeploy:

```bash
scripts/predeploy_check.sh
```

- [ ] Run compose config:

```bash
docker compose --env-file .env.server.example config --quiet
```

- [ ] Run lint and diff hygiene:

```bash
ruff check src scripts tests
git diff --check
```

- [ ] Review admin pages locally:

```bash
ADMIN_DB_PATH=var/admin.sqlite3 \
ADMIN_OWNER_PASSWORD=admin-local \
ADMIN_SESSION_SECRET=local-admin-session-secret-please-change \
ADMIN_SECRET_MASTER_KEY=NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY= \
ADMIN_COOKIE_SECURE=false \
PYTHONPATH=src python3 -m uvicorn translator_service.api:create_app --factory --host 127.0.0.1 --port 62062
```

Open:

```text
http://127.0.0.1:62062/admin/login
```

Check:

- Integrations shows Telegram env fallback when token is in env.
- AI Providers shows DeepSeek env fallback count.
- Live Monitor counts running jobs from Operations.
- Operations `Logs` opens `/admin/logs/{run_id}`.
- Logs can show more than 100 runs with `limit=200`.
- Activity date filters include the selected end date.

---

## Execution Recommendation

Use subagents:

- Agent A: Tasks 2, 7, 8, 10 (admin read/UI/data-flow, low conflict if scoped carefully).
- Agent B: Tasks 3, 4, 5, 6 (admin env/bootstrap/live/operations).
- Main session: Tasks 1 and 9, because deployment and scheduler backend decisions need tighter coordination.

Checkpoint after Tasks 1-4, then after Tasks 5-8, then decide Task 9 implementation mode before final verification.
