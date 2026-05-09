# Admin Practical Operations Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the admin console from a skeleton into a practical owner/operator console for daily service control.

**Architecture:** Keep the console service-level, not Telegram-specific. Build small read-model slices that feed server-rendered admin pages and JSON APIs. Sensitive actions remain explicit, audited, CSRF-protected, and unavailable until role/auth work is ready.

**Tech Stack:** FastAPI admin router, server-rendered HTML/CSS in `translator_service.admin.views`, SQLite admin stores, translation run logs, user activity store, existing job/worker abstractions, optional host metrics through `psutil`.

---

## Scope Decision

This roadmap covers several independent subsystems:

1. Overview Action Center.
2. Jobs and queue operations.
3. Token/cost analytics.
4. Provider health.
5. Alerts.
6. Backups and recovery visibility.
7. Environment safety banner.

Do not implement all of this in one coding pass. Each task below is a shippable
slice. Before implementing each slice, create focused failing tests for that
slice, then implement the smallest code needed to pass.

## File Map

- Modify: `src/translator_service/admin/routes.py`
  - Add routes and JSON APIs for each new slice.
- Modify: `src/translator_service/admin/views.py`
  - Render new admin pages, overview cards, tables, and warnings.
- Modify: `src/translator_service/admin/live.py`
  - Reuse server and translation snapshot data where useful.
- Create: `src/translator_service/admin/action_center.py`
  - Build actionable owner-facing issues from existing stores.
- Create: `src/translator_service/admin/costs.py`
  - Aggregate token usage and estimated cost from translation run logs.
- Create: `src/translator_service/admin/provider_health.py`
  - Normalize AI provider key pool status and future validation results.
- Create: `src/translator_service/admin/alerts.py`
  - Define alert rules and alert read model.
- Create: `src/translator_service/admin/backups.py`
  - Show backup readiness/status without destructive actions.
- Modify: `docs/superpowers/specs/2026-05-08-folioloom-admin-console-design.md`
  - Record each implemented slice.
- Tests:
  - `tests/test_admin_action_center.py`
  - `tests/test_admin_costs.py`
  - `tests/test_admin_provider_health.py`
  - `tests/test_admin_alerts.py`
  - `tests/test_admin_backups.py`
  - Extend `tests/test_admin_routes.py`

---

### Task 1: Environment Safety Banner

**Why first:** It prevents mistakes once the same console exists for dev, stable,
and production.

**Files:**
- Modify: `src/translator_service/admin/views.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing route test**

Add to `tests/test_admin_routes.py`:

```python
def test_admin_shell_shows_environment_badge(self):
    client = TestClient(
        create_app(
            settings=Settings(
                environment="stable",
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
        )
    )
    client.post("/admin/login", data={"password": "owner-pass"})

    response = client.get("/admin/overview")

    self.assertEqual(response.status_code, 200)
    self.assertIn("stable", response.text)
    self.assertIn("environment-badge", response.text)
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes.AdminRoutesTest.test_admin_shell_shows_environment_badge
```

Expected: FAIL because no environment badge exists.

- [ ] **Step 3: Implement shell badge**

Pass `settings.environment` from `_protected_page` into `admin_page`, render a
small badge near the page title, and style it clearly.

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes
python3 -m ruff check --no-cache src/translator_service/admin tests/test_admin_routes.py
```

Expected: tests pass and ruff passes.

---

### Task 2: Overview Action Center

**Why second:** This makes Overview useful immediately.

**Files:**
- Create: `src/translator_service/admin/action_center.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_action_center.py`
- Extend: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing read-model tests**

Create `tests/test_admin_action_center.py`:

```python
import unittest

from translator_service.admin.action_center import build_action_center
from translator_service.admin.integrations import DEFAULT_INTEGRATION_REGISTRY


class AdminActionCenterTest(unittest.TestCase):
    def test_flags_missing_required_integration_connections_and_failed_jobs(self):
        center = build_action_center(
            integration_summaries=DEFAULT_INTEGRATION_REGISTRY.list_summaries(),
            failed_today=3,
            tokens_today=250_000,
            disk_percent=91.0,
        )

        self.assertTrue(any(item.key == "integrations_missing" for item in center.items))
        self.assertTrue(any(item.key == "failed_translations" for item in center.items))
        self.assertTrue(any(item.key == "disk_high" for item in center.items))

    def test_empty_state_when_everything_is_healthy(self):
        center = build_action_center(
            integration_summaries=(),
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
        )

        self.assertEqual(center.items, ())
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_action_center
```

Expected: import failure for missing module.

- [ ] **Step 3: Implement minimal read model**

Create:

```python
@dataclass(frozen=True)
class ActionItem:
    key: str
    severity: str
    title: str
    detail: str
    href: str

@dataclass(frozen=True)
class ActionCenter:
    items: tuple[ActionItem, ...]
```

Implement rules:

- missing required integrations -> `/admin/integrations`;
- failed translations today > 0 -> `/admin/logs?status=failed`;
- tokens today above configurable first hardcoded threshold -> `/admin/live`;
- disk percent >= 85 -> `/admin/live`;
- no DeepSeek keys -> `/admin/ai-providers`.

- [ ] **Step 4: Render on Overview**

Replace the placeholder Overview copy with:

- health summary cards;
- action center list;
- links to the relevant pages.

- [ ] **Step 5: Verify**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_action_center tests.test_admin_routes
python3 -m ruff check --no-cache src/translator_service/admin tests/test_admin_action_center.py tests/test_admin_routes.py
```

---

### Task 3: Jobs And Queue Screen

**Why third:** This gives the admin an operational “what is stuck?” screen.

**Files:**
- Modify: `src/translator_service/admin/operations.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_operations.py`
- Extend: `tests/test_admin_routes.py`

- [ ] **Step 1: Add tests for job rows**

Extend `tests/test_admin_operations.py` with rows containing:

- queued job;
- running job with active worker;
- failed job with safe error excerpt;
- ready job.

Assert retry/cancel flags and safe redaction still work.

- [ ] **Step 2: Render jobs table**

`/admin/operations/jobs` should show:

- state;
- job id;
- order id;
- started/updated;
- fragments completed/total;
- total tokens;
- worker ids;
- safe error excerpt;
- action placeholders: `Retry`, `Cancel` disabled until endpoints are wired.

- [ ] **Step 3: Add log links**

If a translation run exists for a job, link to `/admin/logs`.

- [ ] **Step 4: Verify**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_operations tests.test_admin_routes
python3 -m ruff check --no-cache src/translator_service/admin tests/test_admin_operations.py tests/test_admin_routes.py
```

---

### Task 4: Token Spend And Cost Analytics

**Why fourth:** Token spend is the earliest financial control before Billing.

**Files:**
- Create: `src/translator_service/admin/costs.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_costs.py`
- Extend: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing aggregation tests**

Create tests that build sample translation logs and assert:

- tokens today;
- tokens last 7 days;
- estimated cost;
- top expensive runs;
- per-user totals when `user_id` exists.

- [ ] **Step 2: Implement cost model**

Use configurable defaults first:

```python
input_usd_per_million = 0.28
output_usd_per_million = 1.10
```

Keep exact rates later configurable in Settings/Admin Settings.

- [ ] **Step 3: Add Costs page**

Route:

- `/admin/costs`
- `/admin/api/costs`

UI:

- today;
- last 7 days;
- month-to-date;
- most expensive runs;
- top users by tokens.

- [ ] **Step 4: Verify**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_costs tests.test_admin_routes
python3 -m ruff check --no-cache src/translator_service/admin tests/test_admin_costs.py tests/test_admin_routes.py
```

---

### Task 5: Provider Health

**Why fifth:** The admin needs to know whether DeepSeek/key pool is healthy.

**Files:**
- Create: `src/translator_service/admin/provider_health.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_provider_health.py`

- [ ] **Step 1: Test provider status read model**

Cover:

- no keys configured;
- keys configured;
- disabled key;
- future cooldown/error metadata placeholder;
- never exposes raw key value.

- [ ] **Step 2: Add health cards to AI Providers**

For each provider:

- active key count;
- disabled key count;
- last validation status;
- last error excerpt;
- “Test key” placeholder button disabled until validation endpoint exists.

- [ ] **Step 3: Verify**

Run provider health and routes tests.

---

### Task 6: Alerts MVP

**Why sixth:** The admin should not have to stare at the panel.

**Files:**
- Create: `src/translator_service/admin/alerts.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_alerts.py`

- [ ] **Step 1: Define alert rules**

MVP rules:

- disk >= 85%;
- failed jobs today >= 3;
- no active AI provider key;
- tokens today >= threshold;
- bot/worker heartbeat stale when worker store is connected.

- [ ] **Step 2: Add Alerts area**

Start as read-only:

- alert name;
- severity;
- current value;
- threshold;
- recommended action;
- link to relevant page.

- [ ] **Step 3: Defer delivery channels**

Do not send Telegram/email yet. Add reserved model fields for delivery channel
and `enabled`.

---

### Task 7: Backups And Recovery Visibility

**Why seventh:** Before real users/payments, we need operational confidence.

**Files:**
- Create: `src/translator_service/admin/backups.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_backups.py`
- Create: `docs/deployment/backup-restore-runbook.md`

- [ ] **Step 1: Read-only backup status**

Show:

- expected Docker volumes;
- whether configured paths exist;
- approximate sizes;
- last backup marker file if present.

- [ ] **Step 2: No destructive controls**

Do not add restore/delete buttons in MVP.

- [ ] **Step 3: Write runbook**

Document:

- `docker compose exec postgres pg_dump`;
- `docker run --rm -v ... tar czf`;
- restore steps;
- safety warnings.

---

## Recommended Execution Order

1. Task 1: Environment Safety Banner.
2. Task 2: Overview Action Center.
3. Task 3: Jobs And Queue Screen.
4. Task 4: Token Spend And Cost Analytics.
5. Task 5: Provider Health.
6. Task 6: Alerts MVP.
7. Task 7: Backups And Recovery Visibility.

## Verification Before Completion

After each task:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes
python3 -m ruff check --no-cache src/translator_service/admin tests/test_admin_routes.py
```

After all tasks in this roadmap:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_rbac \
  tests.test_admin_audit \
  tests.test_admin_settings \
  tests.test_admin_secrets \
  tests.test_admin_auth \
  tests.test_admin_integrations \
  tests.test_admin_integration_connections \
  tests.test_admin_ai_provider_keys \
  tests.test_admin_operations \
  tests.test_admin_translation_logs \
  tests.test_admin_live_monitor \
  tests.test_admin_routes \
  tests.test_api \
  tests.test_config

python3 -m ruff check --no-cache src/translator_service/admin src/translator_service/api.py tests/test_admin_*.py tests/test_config.py
docker compose --env-file .env.example config --quiet
```

## Self-Review

- Spec coverage: this roadmap covers the practical admin additions identified
  after reviewing the current console: action center, jobs, costs, provider
  health, alerts, backups, and environment safety.
- Placeholders: destructive actions, terminal access, real alert delivery, and
  full billing are intentionally excluded from this roadmap.
- Type consistency: new modules should expose small dataclass read models and
  route functions should keep returning privacy-safe JSON only.
