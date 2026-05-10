# Cost-Aware Beta Safety Phase 4 Implementation Plan


**Goal:** Добавить beta-safe cost-aware scheduling layer: глобальный kill switch, per-user/per-job/global cost caps, reservation-at-enqueue, idempotent usage accounting и админскую видимость расходов без raw document text.

**Architecture:** Phase 4 не превращает FolioLoom в платёжную систему и не добавляет paid ledger. Она добавляет отдельный safety guard поверх существующих persistent jobs: job получает безопасную cost reservation перед постановкой в очередь, worker/scheduler записывает фактический usage по work-unit idempotently, а scheduler runner не claims новые units, когда глобальная пауза или budget cap закрыли систему.

**Tech Stack:** Python 3.13, `unittest`, SQLite admin/runtime store, PostgreSQL scheduler remains primary for work-unit correctness, existing FastAPI admin routes/views, existing bot runtime and worker/scheduler runner.

---

## Scope

Фаза 4 реализует:

- admin kill switch для новых claims и новых uploads/jobs;
- live-editable beta safety caps через существующий admin settings store;
- оценку стоимости job перед enqueue без хранения текста документа;
- atomic reservation-at-enqueue, чтобы burst uploads не пробивали дневной/месячный лимит;
- release reservation на cancel/rejected/failed-before-start paths;
- idempotent actual usage accounting по `work_unit_id` после успешного completion;
- global budget guard в scheduler runner перед claim;
- админскую страницу/API с consumed/reserved/remaining, users near cap, kill switch state;
- warning в live/action center при 80% лимита, reached cap и active kill switch;
- тесты на caps, idempotency, cancel/release, scheduler pause, admin visibility и no raw text.

Фаза 4 не реализует:

- Telegram Stars/XTR;
- paid user ledger, reservation/capture/refund для платежей;
- distributed Redis locks для scheduler correctness;
- raw prompt/translation logging;
- автоматическое списание денег с пользователя;
- сложный predictive scheduler, который сортирует очередь по цене внутри PostgreSQL query.

## Design Decisions

1. **Reservation at enqueue:** Caps проверяются до того, как job станет исполнимой. Это защищает beta от burst uploads лучше, чем попытка остановить систему только после фактических токенов.
2. **Actual usage is idempotent per work unit:** Повторный completion после lease race или retry не должен удваивать стоимость.
3. **Scheduler sees global stop, not raw budgets per candidate:** Per-user/per-job fairness уже есть в scheduler. Phase 4 добавляет глобальный budget/kill guard перед claim, а per-user/per-job caps применяются при enqueue/resume.
4. **Admin settings are live:** Kill switch и caps должны применяться без restart. Env values служат bootstrap defaults.
5. **Safe metadata only:** В stores/admin/logs попадают только `job_id`, `user_id`, counts, estimated/actual cost, status/reason codes. File names в existing admin остаются как сейчас, но raw document text, prompts, translations и provider secrets не пишутся.
6. **PostgreSQL-first scheduler remains intact:** Work-unit claim/lease correctness не зависит от Redis и не переносится в SQLite safety store.

## File Structure

- Create `src/translator_service/beta_safety.py`: pure cost/rate/limit decision model, safe reason codes and guard protocol.
- Create `src/translator_service/beta_safety_store.py`: SQLite tables for reservations and work-unit usage events; atomic reserve/release/consume operations.
- Create `src/translator_service/admin/beta_safety_settings.py`: live setting definitions and typed settings loader.
- Modify `src/translator_service/config.py`: env bootstrap defaults for beta safety settings.
- Modify `.env.server.example`: documented safe defaults.
- Modify `src/translator_service/bot/runtime.py`: construct safety guard/store/settings and inject into bot service and scheduler runner.
- Modify `src/translator_service/bot_translation_service.py`: enforce guard when persistent job is created, release reservations on cancel/failure-before-work, user-safe rejection messages.
- Modify `src/translator_service/worker.py`: optional callback/hook for completed work-unit usage accounting in direct persistent execution paths.
- Modify `src/translator_service/scheduler_runner.py`: global safety guard before claim and idempotent usage event after claimed completion.
- Modify `src/translator_service/admin/routes.py`: settings update endpoints/API summary for beta safety.
- Modify `src/translator_service/admin/views.py`: settings controls, costs budget summary, live warning fragments.
- Modify `src/translator_service/admin/live.py` or `src/translator_service/admin/action_center.py`: budget degradation warnings.
- Create `tests/test_beta_safety.py`
- Create `tests/test_beta_safety_store.py`
- Modify `tests/test_config.py`
- Modify `tests/test_server_deployment_config.py`
- Modify `tests/test_translation_jobs.py`
- Modify `tests/test_job_runner.py`
- Modify `tests/test_scheduler_runner.py`
- Modify `tests/test_admin_routes.py`
- Modify `tests/test_admin_live_monitor.py`
- Modify `CURRENT_PROJECT_STATE.md`, `README.project.md`, `README.md`, `DOCUMENT_INDEX.md`, `docs/restart/release-gates.md`, `docs/deployment/admin-vps-runbook.md`

## Runtime Vocabulary

Use stable reason/status codes:

```python
BETA_SAFETY_ALLOWED = "allowed"
BETA_SAFETY_KILL_SWITCH = "kill_switch"
BETA_SAFETY_GLOBAL_DAILY_CAP = "global_daily_cap"
BETA_SAFETY_GLOBAL_MONTHLY_CAP = "global_monthly_cap"
BETA_SAFETY_USER_DAILY_CAP = "user_daily_cap"
BETA_SAFETY_USER_MONTHLY_CAP = "user_monthly_cap"
BETA_SAFETY_USER_DAILY_JOB_LIMIT = "user_daily_job_limit"
BETA_SAFETY_JOB_ESTIMATE_CAP = "job_estimate_cap"
BETA_SAFETY_RESERVATION_EXISTS = "reservation_exists"
```

Use stable reservation states:

```python
RESERVATION_ACTIVE = "active"
RESERVATION_RELEASED = "released"
RESERVATION_CONSUMED = "consumed"
```

## Safe Beta Defaults

Add these defaults to `.env.server.example` and `config.py`:

```env
BETA_TRANSLATIONS_PAUSED=false
BETA_GLOBAL_DAILY_COST_CAP_USD=5.00
BETA_GLOBAL_MONTHLY_COST_CAP_USD=50.00
BETA_USER_DAILY_COST_CAP_USD=1.00
BETA_USER_MONTHLY_COST_CAP_USD=10.00
BETA_USER_DAILY_JOB_LIMIT=3
BETA_MAX_JOB_ESTIMATED_COST_USD=2.00
BETA_COST_INPUT_USD_PER_MILLION=0.28
BETA_COST_OUTPUT_USD_PER_MILLION=1.10
BETA_COST_WARNING_FRACTION=0.80
```

Admin live editable:

- `BETA_TRANSLATIONS_PAUSED`
- `BETA_GLOBAL_DAILY_COST_CAP_USD`
- `BETA_GLOBAL_MONTHLY_COST_CAP_USD`
- `BETA_USER_DAILY_COST_CAP_USD`
- `BETA_USER_MONTHLY_COST_CAP_USD`
- `BETA_USER_DAILY_JOB_LIMIT`
- `BETA_MAX_JOB_ESTIMATED_COST_USD`
- `BETA_COST_WARNING_FRACTION`

Restart-only:

- `BETA_COST_INPUT_USD_PER_MILLION`
- `BETA_COST_OUTPUT_USD_PER_MILLION`

Reason: model/provider price changes are operationally rare and should be reviewed deliberately. Kill switch and caps are day-to-day beta operations.

---

## Task 1: Pure Beta Safety Decision Model

**Files:**

- Create `src/translator_service/beta_safety.py`
- Create `tests/test_beta_safety.py`

- [x] **Step 1: Write failing tests for cost estimation and cap decisions**

Create `tests/test_beta_safety.py`:

```python
import unittest

from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BETA_SAFETY_JOB_ESTIMATE_CAP,
    BETA_SAFETY_KILL_SWITCH,
    BETA_SAFETY_USER_DAILY_CAP,
    BetaSafetyLimits,
    BetaSafetyRates,
    BudgetSnapshot,
    JobCostEstimate,
    decide_beta_safety,
    estimate_cost_usd,
)


class BetaSafetyDecisionTest(unittest.TestCase):
    def test_estimates_cost_from_prompt_and_completion_tokens(self):
        rates = BetaSafetyRates(
            input_usd_per_million=0.28,
            output_usd_per_million=1.10,
        )

        self.assertEqual(
            estimate_cost_usd(
                prompt_tokens=1_000_000,
                completion_tokens=500_000,
                rates=rates,
            ),
            0.83,
        )

    def test_allows_when_estimate_fits_remaining_budget(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.001,
            ),
            limits=BetaSafetyLimits(
                translations_paused=False,
                global_daily_cost_cap_usd=5.0,
                global_monthly_cost_cap_usd=50.0,
                user_daily_cost_cap_usd=1.0,
                user_monthly_cost_cap_usd=10.0,
                user_daily_job_limit=3,
                max_job_estimated_cost_usd=2.0,
                warning_fraction=0.8,
            ),
            budget=BudgetSnapshot(
                global_daily_reserved_usd=1.0,
                global_daily_consumed_usd=1.0,
                global_monthly_reserved_usd=10.0,
                global_monthly_consumed_usd=10.0,
                user_daily_reserved_usd=0.1,
                user_daily_consumed_usd=0.2,
                user_monthly_reserved_usd=1.0,
                user_monthly_consumed_usd=1.0,
                user_daily_active_jobs=1,
            ),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_ALLOWED)

    def test_blocks_when_kill_switch_is_active(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.001,
            ),
            limits=BetaSafetyLimits(translations_paused=True),
            budget=BudgetSnapshot(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_KILL_SWITCH)

    def test_blocks_when_job_estimate_exceeds_max_job_cap(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000,
                estimated_cost_usd=3.0,
            ),
            limits=BetaSafetyLimits(max_job_estimated_cost_usd=2.0),
            budget=BudgetSnapshot(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_JOB_ESTIMATE_CAP)

    def test_blocks_when_global_daily_budget_would_be_exceeded(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(global_daily_cost_cap_usd=5.0),
            budget=BudgetSnapshot(
                global_daily_reserved_usd=2.0,
                global_daily_consumed_usd=2.9,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_GLOBAL_DAILY_CAP)

    def test_blocks_when_user_daily_budget_would_be_exceeded(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(user_daily_cost_cap_usd=1.0),
            budget=BudgetSnapshot(
                user_daily_reserved_usd=0.4,
                user_daily_consumed_usd=0.5,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_USER_DAILY_CAP)
```

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_beta_safety
```

Expected: FAIL because `translator_service.beta_safety` does not exist.

- [x] **Step 3: Implement pure model**

Create `src/translator_service/beta_safety.py` with these public shapes:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


BETA_SAFETY_ALLOWED = "allowed"
BETA_SAFETY_KILL_SWITCH = "kill_switch"
BETA_SAFETY_GLOBAL_DAILY_CAP = "global_daily_cap"
BETA_SAFETY_GLOBAL_MONTHLY_CAP = "global_monthly_cap"
BETA_SAFETY_USER_DAILY_CAP = "user_daily_cap"
BETA_SAFETY_USER_MONTHLY_CAP = "user_monthly_cap"
BETA_SAFETY_USER_DAILY_JOB_LIMIT = "user_daily_job_limit"
BETA_SAFETY_JOB_ESTIMATE_CAP = "job_estimate_cap"
BETA_SAFETY_RESERVATION_EXISTS = "reservation_exists"


@dataclass(frozen=True)
class BetaSafetyRates:
    input_usd_per_million: float = 0.28
    output_usd_per_million: float = 1.10


@dataclass(frozen=True)
class BetaSafetyLimits:
    translations_paused: bool = False
    global_daily_cost_cap_usd: float = 5.0
    global_monthly_cost_cap_usd: float = 50.0
    user_daily_cost_cap_usd: float = 1.0
    user_monthly_cost_cap_usd: float = 10.0
    user_daily_job_limit: int = 3
    max_job_estimated_cost_usd: float = 2.0
    warning_fraction: float = 0.8


@dataclass(frozen=True)
class JobCostEstimate:
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class BudgetSnapshot:
    global_daily_reserved_usd: float = 0.0
    global_daily_consumed_usd: float = 0.0
    global_monthly_reserved_usd: float = 0.0
    global_monthly_consumed_usd: float = 0.0
    user_daily_reserved_usd: float = 0.0
    user_daily_consumed_usd: float = 0.0
    user_monthly_reserved_usd: float = 0.0
    user_monthly_consumed_usd: float = 0.0
    user_daily_active_jobs: int = 0


@dataclass(frozen=True)
class BetaSafetyDecision:
    allowed: bool
    reason_code: str
    safe_message: str


class BetaSafetyGuard(Protocol):
    def can_start_new_work(self) -> BetaSafetyDecision:
        ...

    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        ...

    def release_job(self, *, job_id: str, reason: str) -> None:
        ...

    def record_work_unit_usage(
        self,
        *,
        job_id: str,
        user_id: str,
        work_unit_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        ...


def estimate_cost_usd(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    rates: BetaSafetyRates,
) -> float:
    prompt_cost = (max(0, prompt_tokens) / 1_000_000.0) * rates.input_usd_per_million
    completion_cost = (
        max(0, completion_tokens) / 1_000_000.0
    ) * rates.output_usd_per_million
    return round(prompt_cost + completion_cost, 6)
```

Implement `decide_beta_safety(...)` in the same module using this order:

1. kill switch;
2. max estimated job cost;
3. user daily job limit;
4. global daily cap;
5. global monthly cap;
6. user daily cap;
7. user monthly cap;
8. allowed.

Use `reserved + consumed + estimate` for cap comparisons.

- [x] **Step 4: Run model tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_beta_safety
```

Expected: PASS.

- [x] **Step 5: Commit pure model**

Run:

```bash
git add src/translator_service/beta_safety.py tests/test_beta_safety.py
git commit -m "feat: add beta safety decision model"
```

Expected: commit succeeds.

---

## Task 2: SQLite Reservation and Usage Store

**Files:**

- Create `src/translator_service/beta_safety_store.py`
- Create `tests/test_beta_safety_store.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/test_beta_safety_store.py`:

```python
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BetaSafetyLimits,
    BetaSafetyRates,
    JobCostEstimate,
)
from translator_service.beta_safety_store import (
    RESERVATION_ACTIVE,
    RESERVATION_RELEASED,
    SQLiteBetaSafetyStore,
)


class SQLiteBetaSafetyStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "beta-safety.sqlite3"
        self.store = SQLiteBetaSafetyStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_reserve_job_is_atomic_against_global_daily_cap(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        limits = BetaSafetyLimits(global_daily_cost_cap_usd=1.0)
        first = self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.75,
            ),
            limits=limits,
            rates=BetaSafetyRates(),
            now=now,
        )
        second = self.store.reserve_job(
            job_id="job-b",
            user_id="user-2",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.50,
            ),
            limits=limits,
            rates=BetaSafetyRates(),
            now=now,
        )

        self.assertEqual(first.reason_code, BETA_SAFETY_ALLOWED)
        self.assertEqual(second.reason_code, BETA_SAFETY_GLOBAL_DAILY_CAP)

    def test_release_job_removes_active_reservation_from_budget(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.75,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )

        self.store.release_job(job_id="job-a", reason="cancelled", now=now)

        reservation = self.store.get_reservation("job-a")
        summary = self.store.get_budget_summary(user_id="user-1", now=now)
        self.assertEqual(reservation.status, RESERVATION_RELEASED)
        self.assertEqual(summary.user_daily_reserved_usd, 0.0)

    def test_record_work_unit_usage_is_idempotent_by_work_unit_id(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=10_000,
                completion_tokens=5_000,
                estimated_cost_usd=0.01,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )

        self.store.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )
        self.store.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )

        summary = self.store.get_budget_summary(user_id="user-1", now=now)
        self.assertEqual(summary.user_daily_completed_work_units, 1)
        self.assertGreater(summary.user_daily_consumed_usd, 0.0)

    def test_global_start_guard_blocks_when_paused_or_cap_reached(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        paused = self.store.can_start_new_work(
            limits=BetaSafetyLimits(translations_paused=True),
            now=now,
        )
        capped = self.store.can_start_new_work(
            limits=BetaSafetyLimits(global_daily_cost_cap_usd=0.0),
            now=now,
        )

        self.assertFalse(paused.allowed)
        self.assertFalse(capped.allowed)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_beta_safety_store
```

Expected: FAIL because `translator_service.beta_safety_store` does not exist.

- [ ] **Step 3: Implement SQLite store schema and operations**

Create `src/translator_service/beta_safety_store.py` with:

```python
RESERVATION_ACTIVE = "active"
RESERVATION_RELEASED = "released"
RESERVATION_CONSUMED = "consumed"
```

Create tables:

```sql
CREATE TABLE IF NOT EXISTS beta_safety_reservations (
    job_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    estimated_prompt_tokens INTEGER NOT NULL,
    estimated_completion_tokens INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    reserved_at TEXT NOT NULL,
    released_at TEXT,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS beta_safety_usage_events (
    work_unit_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_beta_safety_reservations_user_status
    ON beta_safety_reservations(user_id, status, reserved_at);

CREATE INDEX IF NOT EXISTS idx_beta_safety_usage_user_recorded
    ON beta_safety_usage_events(user_id, recorded_at);
```

Implementation requirements:

- Use one `sqlite3.Connection` with `check_same_thread=False` and an `RLock`, matching local admin stores.
- `reserve_job(...)` opens `BEGIN IMMEDIATE`, reads current budget, calls `decide_beta_safety`, inserts reservation only when allowed, commits.
- `record_work_unit_usage(...)` uses `INSERT OR IGNORE` on `work_unit_id`.
- `release_job(...)` changes only active reservations to released.
- `get_budget_summary(...)` returns consumed/reserved totals for UTC day and UTC month.
- `can_start_new_work(...)` blocks on kill switch and global caps using current consumed + active reserved totals.

- [ ] **Step 4: Run store tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_beta_safety_store
```

Expected: PASS.

- [ ] **Step 5: Commit store**

Run:

```bash
git add src/translator_service/beta_safety_store.py tests/test_beta_safety_store.py
git commit -m "feat: add beta safety reservation store"
```

Expected: commit succeeds.

---

## Task 3: Config and Runtime Wiring

**Files:**

- Create `src/translator_service/admin/beta_safety_settings.py`
- Modify `src/translator_service/config.py`
- Modify `src/translator_service/bot/runtime.py`
- Modify `.env.server.example`
- Modify `tests/test_config.py`
- Modify `tests/test_server_deployment_config.py`

- [ ] **Step 1: Add failing config tests**

Add to `tests/test_config.py`:

```python
def test_beta_safety_defaults_are_safe_for_closed_beta(monkeypatch):
    from translator_service.config import load_settings

    for key in (
        "BETA_TRANSLATIONS_PAUSED",
        "BETA_GLOBAL_DAILY_COST_CAP_USD",
        "BETA_GLOBAL_MONTHLY_COST_CAP_USD",
        "BETA_USER_DAILY_COST_CAP_USD",
        "BETA_USER_MONTHLY_COST_CAP_USD",
        "BETA_USER_DAILY_JOB_LIMIT",
        "BETA_MAX_JOB_ESTIMATED_COST_USD",
        "BETA_COST_INPUT_USD_PER_MILLION",
        "BETA_COST_OUTPUT_USD_PER_MILLION",
        "BETA_COST_WARNING_FRACTION",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings()

    assert settings.beta_translations_paused is False
    assert settings.beta_global_daily_cost_cap_usd == 5.0
    assert settings.beta_global_monthly_cost_cap_usd == 50.0
    assert settings.beta_user_daily_cost_cap_usd == 1.0
    assert settings.beta_user_monthly_cost_cap_usd == 10.0
    assert settings.beta_user_daily_job_limit == 3
    assert settings.beta_max_job_estimated_cost_usd == 2.0
    assert settings.beta_cost_input_usd_per_million == 0.28
    assert settings.beta_cost_output_usd_per_million == 1.10
    assert settings.beta_cost_warning_fraction == 0.8
```

Add to `tests/test_server_deployment_config.py`:

```python
def test_env_server_example_documents_beta_safety_caps():
    example = Path(".env.server.example").read_text(encoding="utf-8")

    assert "BETA_TRANSLATIONS_PAUSED=false" in example
    assert "BETA_GLOBAL_DAILY_COST_CAP_USD=5.00" in example
    assert "BETA_GLOBAL_MONTHLY_COST_CAP_USD=50.00" in example
    assert "BETA_USER_DAILY_COST_CAP_USD=1.00" in example
    assert "BETA_USER_MONTHLY_COST_CAP_USD=10.00" in example
    assert "BETA_USER_DAILY_JOB_LIMIT=3" in example
    assert "BETA_MAX_JOB_ESTIMATED_COST_USD=2.00" in example
```

- [ ] **Step 2: Run config tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_config.py tests/test_server_deployment_config.py -q
```

Expected: FAIL because settings and env defaults do not exist.

- [ ] **Step 3: Add settings and admin setting definitions**

Add fields to settings dataclass in `src/translator_service/config.py` using the defaults above.

Create `src/translator_service/admin/beta_safety_settings.py`:

```python
from __future__ import annotations

from translator_service.admin.settings import (
    AdminSettingDefinition,
    SettingApplyMode,
    SettingValueType,
)
from translator_service.beta_safety import BetaSafetyLimits, BetaSafetyRates


BETA_SAFETY_SETTING_DEFINITIONS = (
    AdminSettingDefinition(
        key="BETA_TRANSLATIONS_PAUSED",
        label="Pause all beta translations",
        value_type=SettingValueType.BOOLEAN,
        apply_mode=SettingApplyMode.LIVE,
        default_value="false",
    ),
    AdminSettingDefinition(
        key="BETA_GLOBAL_DAILY_COST_CAP_USD",
        label="Global daily cost cap USD",
        value_type=SettingValueType.FLOAT,
        apply_mode=SettingApplyMode.LIVE,
        default_value="5.00",
        minimum=0.0,
    ),
    AdminSettingDefinition(
        key="BETA_GLOBAL_MONTHLY_COST_CAP_USD",
        label="Global monthly cost cap USD",
        value_type=SettingValueType.FLOAT,
        apply_mode=SettingApplyMode.LIVE,
        default_value="50.00",
        minimum=0.0,
    ),
    AdminSettingDefinition(
        key="BETA_USER_DAILY_COST_CAP_USD",
        label="Per-user daily cost cap USD",
        value_type=SettingValueType.FLOAT,
        apply_mode=SettingApplyMode.LIVE,
        default_value="1.00",
        minimum=0.0,
    ),
    AdminSettingDefinition(
        key="BETA_USER_MONTHLY_COST_CAP_USD",
        label="Per-user monthly cost cap USD",
        value_type=SettingValueType.FLOAT,
        apply_mode=SettingApplyMode.LIVE,
        default_value="10.00",
        minimum=0.0,
    ),
    AdminSettingDefinition(
        key="BETA_USER_DAILY_JOB_LIMIT",
        label="Per-user daily job limit",
        value_type=SettingValueType.INTEGER,
        apply_mode=SettingApplyMode.LIVE,
        default_value="3",
        minimum=0,
    ),
    AdminSettingDefinition(
        key="BETA_MAX_JOB_ESTIMATED_COST_USD",
        label="Max estimated cost per job USD",
        value_type=SettingValueType.FLOAT,
        apply_mode=SettingApplyMode.LIVE,
        default_value="2.00",
        minimum=0.0,
    ),
    AdminSettingDefinition(
        key="BETA_COST_WARNING_FRACTION",
        label="Budget warning fraction",
        value_type=SettingValueType.FLOAT,
        apply_mode=SettingApplyMode.LIVE,
        default_value="0.80",
        minimum=0.0,
        maximum=1.0,
    ),
)
```

Add helpers:

```python
def load_beta_safety_limits(settings_store, defaults) -> BetaSafetyLimits:
    return BetaSafetyLimits(
        translations_paused=settings_store.get_value(
            "BETA_TRANSLATIONS_PAUSED",
            default=str(defaults.beta_translations_paused).lower(),
        ).lower() == "true",
        global_daily_cost_cap_usd=float(
            settings_store.get_value(
                "BETA_GLOBAL_DAILY_COST_CAP_USD",
                default=str(defaults.beta_global_daily_cost_cap_usd),
            )
        ),
        global_monthly_cost_cap_usd=float(
            settings_store.get_value(
                "BETA_GLOBAL_MONTHLY_COST_CAP_USD",
                default=str(defaults.beta_global_monthly_cost_cap_usd),
            )
        ),
        user_daily_cost_cap_usd=float(
            settings_store.get_value(
                "BETA_USER_DAILY_COST_CAP_USD",
                default=str(defaults.beta_user_daily_cost_cap_usd),
            )
        ),
        user_monthly_cost_cap_usd=float(
            settings_store.get_value(
                "BETA_USER_MONTHLY_COST_CAP_USD",
                default=str(defaults.beta_user_monthly_cost_cap_usd),
            )
        ),
        user_daily_job_limit=int(
            settings_store.get_value(
                "BETA_USER_DAILY_JOB_LIMIT",
                default=str(defaults.beta_user_daily_job_limit),
            )
        ),
        max_job_estimated_cost_usd=float(
            settings_store.get_value(
                "BETA_MAX_JOB_ESTIMATED_COST_USD",
                default=str(defaults.beta_max_job_estimated_cost_usd),
            )
        ),
        warning_fraction=float(
            settings_store.get_value(
                "BETA_COST_WARNING_FRACTION",
                default=str(defaults.beta_cost_warning_fraction),
            )
        ),
    )
```

Use env-only `BetaSafetyRates` from settings.

- [ ] **Step 4: Wire runtime store construction**

In `src/translator_service/bot/runtime.py`, construct `SQLiteBetaSafetyStore` beside the existing admin/runtime SQLite path. Inject it into:

- `BotTranslationService(..., beta_safety_guard=...)`
- scheduler runner loop config if runner construction is centralized there.

Keep guard optional for tests and local development paths that do not configure persistent jobs.

- [ ] **Step 5: Run config/deployment tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_config.py tests/test_server_deployment_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit config/runtime wiring**

Run:

```bash
git add src/translator_service/config.py src/translator_service/admin/beta_safety_settings.py src/translator_service/bot/runtime.py .env.server.example tests/test_config.py tests/test_server_deployment_config.py
git commit -m "feat: wire beta safety configuration"
```

Expected: commit succeeds.

---

## Task 4: Enforce Reservation at Persistent Job Enqueue

**Files:**

- Modify `src/translator_service/bot_translation_service.py`
- Modify `tests/test_translation_jobs.py`

- [ ] **Step 1: Add failing tests for rejection and reservation**

Add a fake guard to `tests/test_translation_jobs.py`:

```python
from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_USER_DAILY_CAP,
    BetaSafetyDecision,
)


class FakeBetaSafetyGuard:
    def __init__(self, decision=None):
        self.decision = decision or BetaSafetyDecision(
            allowed=True,
            reason_code=BETA_SAFETY_ALLOWED,
            safe_message="allowed",
        )
        self.reservations = []
        self.releases = []

    def can_start_new_work(self):
        return self.decision

    def reserve_job(self, *, job_id, user_id, estimate):
        self.reservations.append((job_id, user_id, estimate))
        return self.decision

    def release_job(self, *, job_id, reason):
        self.releases.append((job_id, reason))

    def record_work_unit_usage(self, **kwargs):
        pass
```

Add tests:

```python
def test_persistent_job_reserves_budget_before_queue_execution():
    guard = FakeBetaSafetyGuard()
    service = build_persistent_bot_translation_service(beta_safety_guard=guard)

    job = run_small_persistent_translation(service)

    assert job.id
    assert guard.reservations
    reserved_job_id, reserved_user_id, estimate = guard.reservations[0]
    assert reserved_job_id == job.id
    assert reserved_user_id == str(job.user_telegram_id)
    assert estimate.estimated_cost_usd > 0.0


def test_persistent_job_is_rejected_when_user_budget_is_exceeded():
    guard = FakeBetaSafetyGuard(
        BetaSafetyDecision(
            allowed=False,
            reason_code=BETA_SAFETY_USER_DAILY_CAP,
            safe_message="Daily beta translation budget reached.",
        )
    )
    service = build_persistent_bot_translation_service(beta_safety_guard=guard)

    job = run_small_persistent_translation(service)

    assert job.status is TranslationJobStatus.FAILED
    assert "budget" in (job.error_message or "").lower()
    assert guard.reservations
```

If current test helpers have different names, add equivalent helpers inside the test module. The key assertions are:

- reservation happens after `create_job` and before units are executed/deferred;
- denied reservation returns a user-safe failed/ignored job;
- raw source text is not included in `error_message`.

- [ ] **Step 2: Run translation tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_translation_jobs.py -q
```

Expected: FAIL because `BotTranslationService` does not accept or use `beta_safety_guard`.

- [ ] **Step 3: Add service injection and estimate helper**

Modify `BotTranslationService.__init__`:

```python
from translator_service.beta_safety import (
    BetaSafetyGuard,
    BetaSafetyRates,
    JobCostEstimate,
    estimate_cost_usd,
)

...
beta_safety_guard: BetaSafetyGuard | None = None,
beta_safety_rates: BetaSafetyRates | None = None,
...
self._beta_safety_guard = beta_safety_guard
self._beta_safety_rates = beta_safety_rates or BetaSafetyRates()
```

Add helper near persistent planning helpers:

```python
def _estimate_persistent_plan_cost(
    *,
    fragment_count: int,
    max_fragment_chars: int,
    rates: BetaSafetyRates,
) -> JobCostEstimate:
    prompt_tokens = max(1, math.ceil((fragment_count * max_fragment_chars) / 4))
    completion_tokens = prompt_tokens
    return JobCostEstimate(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimate_cost_usd(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            rates=rates,
        ),
    )
```

This estimate is intentionally conservative for beta safety. It does not inspect or store raw text.

- [ ] **Step 4: Enforce reservation in persistent path**

Immediately after persistent `plan.job` is created and before work units are executed/deferred:

```python
if self._beta_safety_guard is not None:
    decision = self._beta_safety_guard.reserve_job(
        job_id=plan.job.id,
        user_id=str(pending.user_telegram_id),
        estimate=_estimate_persistent_plan_cost(
            fragment_count=total_fragments,
            max_fragment_chars=self._max_fragment_chars,
            rates=self._beta_safety_rates,
        ),
    )
    if not decision.allowed:
        self._persistent_job_store.mark_job_interrupted(plan.job.id)
        safe_error = _beta_safety_user_error(decision.reason_code)
        _finish_run_logger(
            run_logger,
            status=TranslationJobStatus.FAILED.value,
            result_file_name=None,
            error_message=safe_error,
        )
        return _failed_translation_job(
            pending=pending,
            document_kind=document_kind,
            error_message=safe_error,
            job_id=plan.job.id,
        )
```

Add `_beta_safety_user_error(reason_code: str) -> str` with safe fixed strings:

```python
def _beta_safety_user_error(reason_code: str) -> str:
    if reason_code == "kill_switch":
        return "Beta translations are temporarily paused by the operator."
    if reason_code.endswith("_cap") or reason_code == "user_daily_job_limit":
        return "The beta translation budget is temporarily exhausted."
    return "This translation cannot be started under the current beta safety limits."
```

- [ ] **Step 5: Release reservation on cancel before completion**

In persistent cancel/failure-before-assembly paths, call:

```python
if self._beta_safety_guard is not None:
    self._beta_safety_guard.release_job(job_id=plan.job.id, reason="cancelled")
```

Use reasons `cancelled`, `failed_before_completion`, `security_threshold`.

- [ ] **Step 6: Run translation tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_translation_jobs.py tests/test_job_runner.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit bot enqueue guard**

Run:

```bash
git add src/translator_service/bot_translation_service.py tests/test_translation_jobs.py tests/test_job_runner.py
git commit -m "feat: reserve beta budget before persistent enqueue"
```

Expected: commit succeeds.

---

## Task 5: Worker and Scheduler Usage Accounting

**Files:**

- Modify `src/translator_service/worker.py`
- Modify `src/translator_service/scheduler_runner.py`
- Modify `tests/test_scheduler_runner.py`
- Modify `tests/test_persistent_jobs.py`

- [ ] **Step 1: Add failing scheduler runner tests**

Add to `tests/test_scheduler_runner.py`:

```python
from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BetaSafetyDecision,
)


class FakeSchedulerSafetyGuard:
    def __init__(self, start_decision=None):
        self.start_decision = start_decision or BetaSafetyDecision(
            allowed=True,
            reason_code=BETA_SAFETY_ALLOWED,
            safe_message="allowed",
        )
        self.usage_events = []

    def can_start_new_work(self):
        return self.start_decision

    def reserve_job(self, **kwargs):
        return self.start_decision

    def release_job(self, **kwargs):
        pass

    def record_work_unit_usage(self, **kwargs):
        self.usage_events.append(kwargs)
```

Add tests:

```python
def test_scheduler_does_not_claim_when_beta_safety_blocks_new_work():
    guard = FakeSchedulerSafetyGuard(
        BetaSafetyDecision(
            allowed=False,
            reason_code=BETA_SAFETY_GLOBAL_DAILY_CAP,
            safe_message="Global cap reached.",
        )
    )
    store, storage, translator = build_scheduler_fixture_with_one_pending_unit()

    summary = run_scheduler_once(
        store=store,
        storage=storage,
        worker_id="worker-1",
        translator=translator,
        limits=SchedulerLimits(max_active_units_global=1),
        lease_seconds=60,
        max_parallel_units=1,
        beta_safety_guard=guard,
    )

    assert summary.completed_units == 0
    assert store.claim_next_scheduled_work_unit(
        worker_id="probe",
        lease_seconds=60,
        limits=SchedulerLimits(max_active_units_global=1),
    ) is not None


def test_scheduler_records_usage_after_successful_claim_completion():
    guard = FakeSchedulerSafetyGuard()
    store, storage, translator = build_scheduler_fixture_with_one_pending_unit(
        prompt_tokens=7,
        completion_tokens=5,
    )

    summary = run_scheduler_once(
        store=store,
        storage=storage,
        worker_id="worker-1",
        translator=translator,
        limits=SchedulerLimits(max_active_units_global=1),
        lease_seconds=60,
        max_parallel_units=1,
        beta_safety_guard=guard,
    )

    assert summary.completed_units == 1
    assert len(guard.usage_events) == 1
    assert guard.usage_events[0]["prompt_tokens"] == 7
    assert guard.usage_events[0]["completion_tokens"] == 5
```

If existing fixture names differ, implement local fixtures in the test module using the existing in-memory SQLite store and local object storage helpers.

- [ ] **Step 2: Run scheduler runner tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_scheduler_runner.py -q
```

Expected: FAIL because `run_scheduler_once` has no `beta_safety_guard`.

- [ ] **Step 3: Add guard to scheduler runner**

Modify `run_scheduler_once(..., beta_safety_guard: BetaSafetyGuard | None = None)`.

Before serial or parallel claim loops:

```python
if beta_safety_guard is not None:
    decision = beta_safety_guard.can_start_new_work()
    if not decision.allowed:
        logger.warning(
            "Scheduler skipped claims due to beta safety guard: reason=%s",
            decision.reason_code,
        )
        assembled_jobs = assemble_due_jobs(store=store, storage=storage)
        return SchedulerRunOnceSummary(
            completed_units=0,
            failed_units=0,
            assembled_jobs=assembled_jobs,
        )
```

After `complete_claimed_work_unit(...)` succeeds and `completed.status.value in {"translated", "cached"}`:

```python
if beta_safety_guard is not None:
    job = store.get_job(claim.job_id)
    if job is not None:
        beta_safety_guard.record_work_unit_usage(
            job_id=claim.job_id,
            user_id=job.user_id,
            work_unit_id=claim.work_unit_id,
            prompt_tokens=completed.prompt_tokens,
            completion_tokens=completed.completion_tokens,
        )
```

Apply the same usage callback to serial scheduled path by adding an optional callback parameter to `run_next_scheduled_stored_text_work_unit` or by wrapping completion in scheduler runner where possible.

- [ ] **Step 4: Add direct worker hook**

Modify direct persistent worker functions in `src/translator_service/worker.py` with optional:

```python
usage_completed_callback: Callable[[PersistentWorkUnit], None] | None = None
```

Invoke it only after successful, non-stale completion. This keeps Telegram inline persistent execution and scheduler execution consistent.

- [ ] **Step 5: Run worker/scheduler tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_scheduler_runner.py tests/test_worker.py tests/test_persistent_jobs.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit accounting hooks**

Run:

```bash
git add src/translator_service/worker.py src/translator_service/scheduler_runner.py tests/test_scheduler_runner.py tests/test_persistent_jobs.py
git commit -m "feat: account beta usage from completed work units"
```

Expected: commit succeeds.

---

## Task 6: Admin Settings, Costs Summary and Live Warnings

**Files:**

- Modify `src/translator_service/admin/routes.py`
- Modify `src/translator_service/admin/views.py`
- Modify `src/translator_service/admin/costs.py`
- Modify `src/translator_service/admin/live.py` or `src/translator_service/admin/action_center.py`
- Modify `tests/test_admin_routes.py`
- Modify `tests/test_admin_live_monitor.py`

- [ ] **Step 1: Add failing admin route tests**

Add to `tests/test_admin_routes.py`:

```python
def test_admin_settings_show_beta_safety_controls(client):
    response = client.get("/admin/settings")

    assert response.status_code == 200
    body = response.text
    assert "Pause all beta translations" in body
    assert "Global daily cost cap USD" in body
    assert "Per-user daily cost cap USD" in body


def test_costs_api_includes_beta_budget_summary(client, admin_settings_store):
    admin_settings_store.set_value("BETA_GLOBAL_DAILY_COST_CAP_USD", "5.00")
    admin_settings_store.set_value("BETA_USER_DAILY_COST_CAP_USD", "1.00")

    response = client.get("/admin/api/costs")

    assert response.status_code == 200
    payload = response.json()
    assert "beta_safety" in payload
    assert payload["beta_safety"]["global_daily_cap_usd"] == 5.0
    assert "global_daily_remaining_usd" in payload["beta_safety"]


def test_admin_can_pause_beta_translations_without_restart(client):
    response = client.post(
        "/admin/settings",
        data={"BETA_TRANSLATIONS_PAUSED": "true"},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    settings_response = client.get("/admin/settings")
    assert "checked" in settings_response.text
```

Add to `tests/test_admin_live_monitor.py`:

```python
def test_live_monitor_warns_when_beta_budget_nears_cap(client, beta_safety_store):
    beta_safety_store.seed_budget_for_test(
        user_id="123",
        consumed_usd=4.1,
        reserved_usd=0.0,
        day="2026-05-10",
    )

    response = client.get("/admin/live")

    assert response.status_code == 200
    assert "budget" in response.text.lower()
    assert "warning" in response.text.lower()
```

If current fixtures do not expose `beta_safety_store`, add route factory dependency injection matching existing admin runtime stores.

- [ ] **Step 2: Run admin tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_admin_routes.py tests/test_admin_live_monitor.py -q
```

Expected: FAIL because admin budget summary/settings are not wired.

- [ ] **Step 3: Extend settings page**

In `admin/routes.py`, include `BETA_SAFETY_SETTING_DEFINITIONS` in the settings definitions list. Persist submitted values through existing `SQLiteAdminSettingsStore.set_value(...)`.

In `admin/views.py`, render beta safety controls in the existing settings page as operational controls, not billing controls. Use fixed labels from definitions and no raw text.

- [ ] **Step 4: Extend costs analytics response**

In `admin/costs.py`, add:

```python
@dataclass(frozen=True)
class BetaSafetyCostSummary:
    translations_paused: bool
    global_daily_cap_usd: float
    global_daily_reserved_usd: float
    global_daily_consumed_usd: float
    global_daily_remaining_usd: float
    global_monthly_cap_usd: float
    global_monthly_reserved_usd: float
    global_monthly_consumed_usd: float
    global_monthly_remaining_usd: float
    warning: bool
```

Build it from `SQLiteBetaSafetyStore.get_budget_summary(...)` and `load_beta_safety_limits(...)`.

In `/admin/api/costs`, include:

```json
{
  "beta_safety": {
    "translations_paused": false,
    "global_daily_cap_usd": 5.0,
    "global_daily_reserved_usd": 0.0,
    "global_daily_consumed_usd": 0.0,
    "global_daily_remaining_usd": 5.0,
    "warning": false
  }
}
```

- [ ] **Step 5: Add live warning**

Add action-center/live warning when:

- `translations_paused` is true;
- `global_daily_consumed + global_daily_reserved >= cap * warning_fraction`;
- `global_monthly_consumed + global_monthly_reserved >= cap * warning_fraction`.

Use short safe messages:

```text
Beta translations are paused.
Daily beta cost budget is near the configured cap.
Monthly beta cost budget is near the configured cap.
```

- [ ] **Step 6: Run admin tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_admin_routes.py tests/test_admin_live_monitor.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit admin UI/API**

Run:

```bash
git add src/translator_service/admin/routes.py src/translator_service/admin/views.py src/translator_service/admin/costs.py src/translator_service/admin/live.py src/translator_service/admin/action_center.py tests/test_admin_routes.py tests/test_admin_live_monitor.py
git commit -m "feat: expose beta safety budgets in admin"
```

Expected: commit succeeds. If only one of `live.py` or `action_center.py` changed, stage the changed file and omit the untouched one.

---

## Task 7: Cancellation, Resume and No Raw Text Regression Coverage

**Files:**

- Modify `tests/test_translation_jobs.py`
- Modify `tests/test_scheduler_runner.py`
- Modify `tests/test_admin_routes.py`

- [ ] **Step 1: Add cancellation release test**

Add to `tests/test_translation_jobs.py`:

```python
def test_cancelled_persistent_job_releases_beta_reservation():
    guard = FakeBetaSafetyGuard()
    service = build_persistent_bot_translation_service(beta_safety_guard=guard)

    job = run_persistent_translation_and_cancel_after_first_unit(service)

    assert job.status is TranslationJobStatus.CANCELLED
    assert guard.releases
    assert guard.releases[-1][1] == "cancelled"
```

- [ ] **Step 2: Add no raw text tests**

Add to `tests/test_admin_routes.py`:

```python
def test_beta_safety_admin_views_do_not_expose_raw_document_text(client, beta_safety_store):
    raw_text = "SECRET RAW DOCUMENT TEXT SHOULD NOT APPEAR"
    beta_safety_store.reserve_job_for_test(
        job_id="job-secret",
        user_id="123",
        estimated_cost_usd=0.10,
    )

    costs = client.get("/admin/costs")
    api = client.get("/admin/api/costs")

    assert costs.status_code == 200
    assert api.status_code == 200
    assert raw_text not in costs.text
    assert raw_text not in api.text
```

This test intentionally does not write raw text into the safety store. It protects the admin path from adding document text later.

- [ ] **Step 3: Add capacity=1 legacy guard test**

Add to `tests/test_scheduler_runner.py`:

```python
def test_beta_safety_guard_preserves_capacity_one_serial_success_path():
    guard = FakeSchedulerSafetyGuard()
    store, storage, translator = build_scheduler_fixture_with_one_pending_unit()

    summary = run_scheduler_once(
        store=store,
        storage=storage,
        worker_id="worker-1",
        translator=translator,
        limits=SchedulerLimits(max_active_units_global=1),
        lease_seconds=60,
        max_parallel_units=1,
        beta_safety_guard=guard,
    )

    assert summary.completed_units == 1
    assert len(guard.usage_events) == 1
```

- [ ] **Step 4: Run regression subset**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_translation_jobs.py tests/test_scheduler_runner.py tests/test_admin_routes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit regression coverage**

Run:

```bash
git add tests/test_translation_jobs.py tests/test_scheduler_runner.py tests/test_admin_routes.py
git commit -m "test: cover beta safety cancellation and redaction"
```

Expected: commit succeeds.

---

## Task 8: Documentation and Release Gates

**Files:**

- Modify `CURRENT_PROJECT_STATE.md`
- Modify `README.project.md`
- Modify `README.md`
- Modify `DOCUMENT_INDEX.md`
- Modify `docs/restart/release-gates.md`
- Modify `docs/deployment/admin-vps-runbook.md`

- [ ] **Step 1: Update current state**

In `CURRENT_PROJECT_STATE.md`, move “Per-user quotas, global cost cap and admin kill switch” from open gaps to implemented Phase 4 beta safety, with this wording:

```markdown
- Phase 4 beta safety is implemented: live admin kill switch, global/user cost caps, job reservations, idempotent work-unit usage accounting and budget warnings. This is an operational beta guard, not a paid billing ledger.
```

- [ ] **Step 2: Update README.project.md**

Add a short “Beta Safety / Cost Guard” section:

```markdown
### Beta Safety / Cost Guard

FolioLoom keeps beta throughput bounded with a cost-aware safety layer:

- new persistent jobs reserve estimated budget before queue execution;
- completed work units record prompt/completion token usage idempotently;
- the scheduler stops claiming new units when the admin kill switch or global caps are active;
- admin pages show consumed, reserved and remaining beta budget;
- no raw document text, prompts, translations or API keys are stored in safety telemetry.

This layer is separate from paid beta billing. Telegram Stars/XTR and a payment ledger remain a separate release gate.
```

- [ ] **Step 3: Update README.md and runbook**

Document env defaults and operator actions:

```markdown
To pause all beta translations without restart, open Admin -> Settings and enable `BETA_TRANSLATIONS_PAUSED`.

For a small closed beta, start with:

- `BETA_GLOBAL_DAILY_COST_CAP_USD=5.00`
- `BETA_GLOBAL_MONTHLY_COST_CAP_USD=50.00`
- `BETA_USER_DAILY_COST_CAP_USD=1.00`
- `BETA_USER_DAILY_JOB_LIMIT=3`
```

In `docs/deployment/admin-vps-runbook.md`, add an incident response section:

```markdown
If provider cost or error rate spikes:

1. Enable `BETA_TRANSLATIONS_PAUSED=true` in Admin -> Settings.
2. Check Admin -> Costs for consumed vs reserved budget.
3. Check Admin -> AI Providers for cooldown/circuit state.
4. Resume only after budget and provider health are understood.
```

- [ ] **Step 4: Update release gates and index**

In `docs/restart/release-gates.md`, mark beta safety guard as done for closed beta, while keeping paid billing ledger as not done.

In `DOCUMENT_INDEX.md`, add the new plan and docs references.

- [ ] **Step 5: Run docs/deployment checks**

Run:

```bash
bash scripts/predeploy_check.sh
```

Expected: PASS.

- [ ] **Step 6: Commit docs**

Run:

```bash
git add CURRENT_PROJECT_STATE.md README.project.md README.md DOCUMENT_INDEX.md docs/restart/release-gates.md docs/deployment/admin-vps-runbook.md
git commit -m "docs: document beta safety cost guard"
```

Expected: commit succeeds.

---

## Task 9: Final Verification

**Files:**

- No code files unless verification finds a concrete bug.

- [ ] **Step 1: Run targeted suite**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_beta_safety.py \
  tests/test_beta_safety_store.py \
  tests/test_config.py \
  tests/test_server_deployment_config.py \
  tests/test_translation_jobs.py \
  tests/test_job_runner.py \
  tests/test_worker.py \
  tests/test_scheduler.py \
  tests/test_scheduler_runner.py \
  tests/test_persistent_jobs.py \
  tests/test_persistent_job_store.py \
  tests/test_postgres_scheduler.py \
  tests/test_admin_routes.py \
  tests/test_admin_live_monitor.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run compile check**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: PASS.

- [ ] **Step 3: Run predeploy check**

Run:

```bash
bash scripts/predeploy_check.sh
```

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: no uncommitted implementation/doc changes.

---

## Implementation Notes for Agents

- Keep all safety telemetry free of raw source text and translated text.
- Do not log API keys, provider request bodies, prompts or document excerpts.
- Keep Redis optional. Do not introduce Redis as a dependency for reservation correctness.
- Do not alter PostgreSQL work-unit claim semantics except for optional guard checks in runner code.
- Preserve Phase 1 fairness and Phase 3 adaptive provider throttling. Cost guard is a gate around starts, not a replacement scheduler.
- Use UTC for budget periods in code and admin summaries.
- If actual usage exceeds estimate, record actual usage and let caps block future starts. Do not kill already completed units retroactively.
- If a job is cancelled while units are active, release remaining reservation after terminal status; idempotent usage events keep completed units counted.
- If admin changes caps while worker is running, next `can_start_new_work()` and next `reserve_job()` must use fresh settings.

## Tradeoffs

- **Reservation estimates are conservative.** This may reject some large documents that would have translated cheaply, but closed beta safety is more important than maximum throughput.
- **Global budget guard before claim is coarse.** It prevents further spend quickly, while keeping scheduler fairness query simple and safe.
- **SQLite safety store is acceptable for the current single-VPS model.** PostgreSQL remains source of truth for work-unit correctness. A future multi-node deployment can move safety tables to PostgreSQL without changing the public `BetaSafetyGuard` protocol.
- **No paid ledger in Phase 4.** This prevents mixing operational safety with billing semantics before Telegram Stars/XTR and refund flows exist.
