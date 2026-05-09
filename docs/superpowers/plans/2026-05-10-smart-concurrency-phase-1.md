# Smart Concurrency Phase 1 Implementation Plan


**Goal:** Реализовать первый production-like срез smart concurrency для FolioLoom: честные scheduler-claims между пользователями и jobs, жесткие beta-safe caps, динамическое ограничение по provider capacity, минимальная admin-наблюдаемость очереди и сохранение гарантий against duplicate/stale work-unit completion.

**Architecture:** PostgreSQL остается source of truth для server runtime; Redis не участвует в correctness. Расширяем текущий scheduler contract вместо замены архитектуры: `SchedulerLimits` становится единым объектом лимитов, SQLite-store сохраняет local/dev parity, `PostgresSchedulerStore.claim_next_scheduled_work_unit()` становится production fairness gate. DeepSeek key scoring, provider degradation UI, AIMD и cost-aware scheduling не смешиваем с Phase 1: они идут отдельными фазами после безопасного scheduler foundation.

**Tech Stack:** Python 3.13, `unittest`, PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`, SQLite fallback, FastAPI admin views, существующий DeepSeek-compatible runtime.

---

## Мой Выбор

Реализуем не “поднять concurrency”, а сначала сделать scheduler справедливым и предсказуемым:

1. Worker считает верхний потолок параллелизма как сейчас: `TRANSLATION_MAX_PARALLEL_UNITS` пересекается с effective provider capacity.
2. Scheduler дополнительно режет этот потолок через global/user/job caps.
3. Claim query выбирает следующий unit по fairness: сначала пользователи с меньшим active load, потом jobs с меньшим active load, затем priority/age/sequence.
4. Provider key pool в Phase 1 не переписываем: он уже умеет arbitrary key count, weights, per-key parallelism и cooldown. Phase 1 только не дает scheduler-у завалить runtime несправедливой очередью.
5. Admin показывает queue pressure без raw document text: depth, oldest pending age, active/running counts.

Это правильный порядок, потому что fairness в scheduler является фундаментом. Если сначала добавить adaptive throttling или сложный key scoring, система все равно сможет несправедливо отдавать все слоты одному huge document или одному heavy user.

## Scope Phase 1

Входит:

- config/env для scheduler caps;
- `SchedulerLimits` с beta-safe defaults;
- worker wiring этих лимитов;
- SQLite claim parity;
- PostgreSQL claim fairness/caps;
- сохранение capacity=1 legacy behavior;
- тесты на duplicate claim, cancel, lease/stale completion через существующие suites;
- минимальные admin operations metrics: queue depth и oldest pending age.

Не входит:

- provider channel leases в PostgreSQL;
- latency/error-aware key scoring;
- AIMD global ramp;
- provider circuit breaker;
- token/cost budget scheduler;
- полноценный DRR/virtual runtime ledger.

Эти части будут отдельными планами Phase 2-4.

## Файлы

- Modify `src/translator_service/scheduler.py`: расширить `SchedulerLimits`.
- Modify `src/translator_service/config.py`: добавить env/settings для scheduler caps.
- Modify `.env.server.example`: задокументировать safe beta defaults.
- Modify `src/translator_service/worker.py`: строить `SchedulerLimits` из settings и effective provider capacity.
- Modify `src/translator_service/persistent_jobs.py`: SQLite per-user caps и fair ordering.
- Modify `src/translator_service/postgres_scheduler.py`: PostgreSQL per-user caps и fair ordering.
- Modify `src/translator_service/admin/operations.py`: derived queue pressure metrics.
- Modify `src/translator_service/admin/views.py`: показать metrics в Operations.
- Modify `README.md`, `README.project.md`, `docs/deployment/admin-vps-runbook.md`: эксплуатационные defaults и модель лимитов.
- Test `tests/test_scheduler.py`, `tests/test_config.py`, `tests/test_worker.py`, `tests/test_persistent_jobs.py`, `tests/test_postgres_scheduler.py`, `tests/test_scheduler_runner.py`, `tests/test_admin_live_monitor.py`, `tests/test_admin_routes.py`, `tests/test_server_deployment_config.py`.

## Safe Beta Defaults

```env
SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL=2
SCHEDULER_MAX_ACTIVE_UNITS_PER_USER=1
SCHEDULER_MAX_ACTIVE_JOBS_PER_USER=1
SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB=1
SCHEDULER_PRIORITY_AGING_SECONDS=1800
```

Эффективная worker capacity:

```text
worker_capacity = min(
    TRANSLATION_MAX_PARALLEL_UNITS,
    provider_effective_capacity,
    SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL
)
```

`provider_effective_capacity` уже зависит от runtime/admin/env keys, `max_parallel_requests`, disabled/cooldown key state и reload.

---

## Task 1: SchedulerLimits Contract

**Files:**

- Modify `src/translator_service/scheduler.py`
- Modify `tests/test_scheduler.py`

- [ ] **Step 1: Добавить failing contract test**

Добавить в `tests/test_scheduler.py` проверку beta defaults:

```python
def test_scheduler_limits_include_beta_fairness_defaults(self):
    limits = SchedulerLimits()

    self.assertEqual(limits.max_active_units_per_job, 1)
    self.assertEqual(limits.max_active_jobs_per_user, 1)
    self.assertEqual(limits.max_active_units_per_user, 1)
    self.assertEqual(limits.max_active_units_global, 2)
    self.assertEqual(limits.max_attempts_per_unit, 3)
    self.assertEqual(limits.priority_aging_seconds, 1800)
```

- [ ] **Step 2: Обновить dataclass**

В `src/translator_service/scheduler.py`:

```python
@dataclass(frozen=True)
class SchedulerLimits:
    max_active_units_per_job: int = 1
    max_active_jobs_per_user: int = 1
    max_active_units_per_user: int = 1
    max_active_units_global: int = 2
    max_attempts_per_unit: int = 3
    priority_aging_seconds: int = 1800
```

- [ ] **Step 3: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_scheduler
```

Expected: OK.

## Task 2: Config and Env Defaults

**Files:**

- Modify `src/translator_service/config.py`
- Modify `.env.server.example`
- Modify `tests/test_config.py`
- Modify `tests/test_server_deployment_config.py`

- [ ] **Step 1: Добавить tests на defaults и env override**

В `tests/test_config.py`:

```python
def test_scheduler_limit_settings_have_safe_beta_defaults(self):
    settings = Settings()

    self.assertEqual(settings.scheduler_max_active_units_global, 2)
    self.assertEqual(settings.scheduler_max_active_units_per_user, 1)
    self.assertEqual(settings.scheduler_max_active_jobs_per_user, 1)
    self.assertEqual(settings.scheduler_max_active_units_per_job, 1)
    self.assertEqual(settings.scheduler_priority_aging_seconds, 1800)


def test_scheduler_limit_settings_can_be_configured_from_environment(self):
    with patch.dict(
        "os.environ",
        {
            "SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL": "8",
            "SCHEDULER_MAX_ACTIVE_UNITS_PER_USER": "2",
            "SCHEDULER_MAX_ACTIVE_JOBS_PER_USER": "2",
            "SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB": "3",
            "SCHEDULER_PRIORITY_AGING_SECONDS": "900",
        },
    ):
        settings = Settings()

    self.assertEqual(settings.scheduler_max_active_units_global, 8)
    self.assertEqual(settings.scheduler_max_active_units_per_user, 2)
    self.assertEqual(settings.scheduler_max_active_jobs_per_user, 2)
    self.assertEqual(settings.scheduler_max_active_units_per_job, 3)
    self.assertEqual(settings.scheduler_priority_aging_seconds, 900)
```

- [ ] **Step 2: Добавить settings fields**

В `src/translator_service/config.py` рядом с scheduler/worker settings:

```python
scheduler_max_active_units_global: int = field(
    default_factory=lambda: max(
        1,
        int(os.getenv("SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL", "2")),
    )
)
scheduler_max_active_units_per_user: int = field(
    default_factory=lambda: max(
        1,
        int(os.getenv("SCHEDULER_MAX_ACTIVE_UNITS_PER_USER", "1")),
    )
)
scheduler_max_active_jobs_per_user: int = field(
    default_factory=lambda: max(
        1,
        int(os.getenv("SCHEDULER_MAX_ACTIVE_JOBS_PER_USER", "1")),
    )
)
scheduler_max_active_units_per_job: int = field(
    default_factory=lambda: max(
        1,
        int(os.getenv("SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB", "1")),
    )
)
scheduler_priority_aging_seconds: int = field(
    default_factory=lambda: max(
        0,
        int(os.getenv("SCHEDULER_PRIORITY_AGING_SECONDS", "1800")),
    )
)
```

- [ ] **Step 3: Добавить `.env.server.example` defaults**

```env
SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL=2
SCHEDULER_MAX_ACTIVE_UNITS_PER_USER=1
SCHEDULER_MAX_ACTIVE_JOBS_PER_USER=1
SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB=1
SCHEDULER_PRIORITY_AGING_SECONDS=1800
```

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_config tests.test_server_deployment_config
```

Expected: OK.

## Task 3: Worker Limit Wiring

**Files:**

- Modify `src/translator_service/worker.py`
- Modify `tests/test_worker.py`

- [ ] **Step 1: Добавить unit test на helper**

```python
def test_worker_builds_scheduler_limits_from_settings(self):
    from translator_service.worker import scheduler_limits_from_settings

    settings = type(
        "Settings",
        (),
        {
            "scheduler_max_active_units_global": 6,
            "scheduler_max_active_units_per_user": 2,
            "scheduler_max_active_jobs_per_user": 1,
            "scheduler_max_active_units_per_job": 2,
            "scheduler_priority_aging_seconds": 600,
        },
    )()

    limits = scheduler_limits_from_settings(settings, effective_global_capacity=4)

    self.assertEqual(limits.max_active_units_global, 4)
    self.assertEqual(limits.max_active_units_per_user, 2)
    self.assertEqual(limits.max_active_jobs_per_user, 1)
    self.assertEqual(limits.max_active_units_per_job, 2)
    self.assertEqual(limits.priority_aging_seconds, 600)
```

- [ ] **Step 2: Добавить helper**

В `src/translator_service/worker.py`:

```python
def scheduler_limits_from_settings(settings, *, effective_global_capacity: int):
    from translator_service.scheduler import SchedulerLimits

    configured_global = max(1, int(settings.scheduler_max_active_units_global))
    return SchedulerLimits(
        max_active_units_per_job=max(1, int(settings.scheduler_max_active_units_per_job)),
        max_active_jobs_per_user=max(1, int(settings.scheduler_max_active_jobs_per_user)),
        max_active_units_per_user=max(1, int(settings.scheduler_max_active_units_per_user)),
        max_active_units_global=max(1, min(configured_global, int(effective_global_capacity))),
        priority_aging_seconds=max(0, int(settings.scheduler_priority_aging_seconds)),
    )
```

В worker `main()` заменить inline `SchedulerLimits(...)` на helper:

```python
limits=scheduler_limits_from_settings(
    settings,
    effective_global_capacity=worker_parallel_units,
)
```

- [ ] **Step 3: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_worker
```

Expected: OK.

## Task 4: SQLite Fairness and User Caps

**Files:**

- Modify `src/translator_service/persistent_jobs.py`
- Modify `tests/test_persistent_jobs.py`

- [ ] **Step 1: Добавить tests**

Добавить helper для jobs с явным `user_id`, затем покрыть два сценария:

```python
def test_scheduled_claim_respects_per_user_active_units_limit(self):
    store = self._memory_store()
    first = _job_with_units_for_user(store, user_id="telegram:42", order_id="order-1")
    second = _job_with_units_for_user(store, user_id="telegram:42", order_id="order-2")
    limits = SchedulerLimits(
        max_active_units_global=4,
        max_active_units_per_user=1,
        max_active_jobs_per_user=2,
        max_active_units_per_job=1,
    )

    first_claim = store.claim_next_scheduled_work_unit("worker-a", 300, limits)
    second_claim = store.claim_next_scheduled_work_unit("worker-b", 300, limits)

    self.assertEqual(first_claim.job_id, first.id)
    self.assertIsNone(second_claim)
    self.assertEqual(store.get_job(second.id).status, PersistentTranslationJobStatus.QUEUED)
```

```python
def test_scheduled_claim_prefers_user_with_fewer_active_units(self):
    store = self._memory_store()
    first = _job_with_units_for_user(store, user_id="telegram:42", order_id="order-1")
    second = _job_with_units_for_user(store, user_id="telegram:77", order_id="order-2")
    limits = SchedulerLimits(
        max_active_units_global=4,
        max_active_units_per_user=2,
        max_active_jobs_per_user=2,
        max_active_units_per_job=1,
    )

    first_claim = store.claim_next_scheduled_work_unit("worker-a", 300, limits)
    second_claim = store.claim_next_scheduled_work_unit("worker-b", 300, limits)

    self.assertEqual(first_claim.job_id, first.id)
    self.assertEqual(second_claim.job_id, second.id)
```

- [ ] **Step 2: Добавить predicates в SQLite candidate SELECT**

В `SQLiteTranslationJobStore.claim_next_scheduled_work_unit()` добавить проверки:

```sql
AND (
    SELECT COUNT(*)
    FROM work_units active
    JOIN translation_jobs active_job ON active_job.id = active.job_id
    WHERE active.status = ?
      AND active_job.user_id = tj.user_id
) < ?
AND (
    SELECT COUNT(DISTINCT active.job_id)
    FROM work_units active
    JOIN translation_jobs active_job ON active_job.id = active.job_id
    WHERE active.status = ?
      AND active_job.user_id = tj.user_id
) < ?
```

- [ ] **Step 3: Заменить ordering**

```sql
ORDER BY
  (
      SELECT COUNT(*)
      FROM work_units active
      JOIN translation_jobs active_job ON active_job.id = active.job_id
      WHERE active.status = ?
        AND active_job.user_id = tj.user_id
  ) ASC,
  (
      SELECT COUNT(DISTINCT active.job_id)
      FROM work_units active
      JOIN translation_jobs active_job ON active_job.id = active.job_id
      WHERE active.status = ?
        AND active_job.user_id = tj.user_id
  ) ASC,
  (
      SELECT COUNT(*)
      FROM work_units active
      WHERE active.job_id = wu.job_id
        AND active.status = ?
  ) ASC,
  tj.priority DESC,
  datetime(tj.created_at),
  wu.sequence
```

Такой же guard добавить в `UPDATE`, чтобы между SELECT и UPDATE не было обхода caps.

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs
```

Expected: OK.

## Task 5: PostgreSQL Fairness and User Caps

**Files:**

- Modify `src/translator_service/postgres_scheduler.py`
- Modify `tests/test_postgres_scheduler.py`

- [ ] **Step 1: Добавить Postgres tests**

Добавить сценарии:

- same user, two jobs, `max_active_units_per_user=1`: второй claim возвращает `None`;
- two users, capacity > 1: второй claim уходит другому user;
- existing duplicate claim/stale completion tests остаются green.

- [ ] **Step 2: Добавить params**

В `PostgresSchedulerStore.claim_next_scheduled_work_unit()`:

```python
max_active_jobs_per_user = max(1, limits.max_active_jobs_per_user)
max_active_units_per_user = max(1, limits.max_active_units_per_user)
```

- [ ] **Step 3: Добавить SQL predicates**

В candidate CTE:

```sql
AND (
    SELECT COUNT(*)
    FROM work_units active
    JOIN translation_jobs active_job ON active_job.id = active.job_id
    WHERE active.status = 'translating'
      AND active_job.user_id = tj.user_id
) < %(max_active_units_per_user)s
AND (
    SELECT COUNT(DISTINCT active.job_id)
    FROM work_units active
    JOIN translation_jobs active_job ON active_job.id = active.job_id
    WHERE active.status = 'translating'
      AND active_job.user_id = tj.user_id
) < %(max_active_jobs_per_user)s
```

Ordering:

```sql
ORDER BY
  (
      SELECT COUNT(*)
      FROM work_units active
      JOIN translation_jobs active_job ON active_job.id = active.job_id
      WHERE active.status = 'translating'
        AND active_job.user_id = tj.user_id
  ) ASC,
  (
      SELECT COUNT(DISTINCT active.job_id)
      FROM work_units active
      JOIN translation_jobs active_job ON active_job.id = active.job_id
      WHERE active.status = 'translating'
        AND active_job.user_id = tj.user_id
  ) ASC,
  (
      SELECT COUNT(*)
      FROM work_units active
      WHERE active.job_id = wu.job_id
        AND active.status = 'translating'
  ) ASC,
  tj.priority DESC,
  tj.created_at,
  wu.sequence
```

Такие же caps добавить в guarded `UPDATE`.

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_postgres_scheduler
```

Expected: OK или integration skipped без `TEST_POSTGRES_DSN`.

## Task 6: Scheduler Runner Behavior

**Files:**

- Modify `tests/test_scheduler_runner.py`
- Modify implementation only if tests reveal regression

- [ ] **Step 1: Уточнить parallel test**

Существующий test на multiple jobs in parallel должен явно использовать разных пользователей, чтобы проверять ожидаемую честную конкуренцию между users.

- [ ] **Step 2: Добавить same-user cap runner test**

```python
def test_run_once_does_not_let_one_user_fill_all_parallel_slots(self):
    with TemporaryDirectory() as temp_dir:
        storage = LocalObjectStorage(Path(temp_dir))
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        _create_single_unit_txt_job(
            store=store,
            storage=storage,
            order_id="order-1",
            file_id="file-1",
            source_text="First paragraph",
            user_id="telegram:42",
        )
        _create_single_unit_txt_job(
            store=store,
            storage=storage,
            order_id="order-2",
            file_id="file-2",
            source_text="Second paragraph",
            user_id="telegram:42",
        )
        translator = BlockingRunnerTranslator(delay_seconds=0.01)

        summary = run_scheduler_once(
            store=store,
            storage=storage,
            worker_id="worker-a",
            translator=translator,
            limits=SchedulerLimits(
                max_active_units_per_job=1,
                max_active_units_per_user=1,
                max_active_jobs_per_user=1,
                max_active_units_global=2,
            ),
            lease_seconds=300,
            max_parallel_units=2,
        )

        self.assertEqual(summary.completed_units, 1)
        self.assertEqual(translator.max_active_calls, 1)
```

- [ ] **Step 3: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_scheduler_runner
```

Expected: OK.

## Task 7: Minimal Operations Queue Metrics

**Files:**

- Modify `src/translator_service/admin/operations.py`
- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_live_monitor.py` or `tests/test_admin_routes.py`

- [ ] **Step 1: Добавить test на queue depth и oldest pending**

```python
def test_operations_overview_reports_queue_depth_and_oldest_pending_age(self):
    operations = build_operations_overview(
        jobs=[
            {
                "id": "job-queued",
                "status": "queued",
                "created_at": datetime(2026, 5, 9, 11, 50, tzinfo=UTC),
                "updated_at": datetime(2026, 5, 9, 11, 55, tzinfo=UTC),
            },
        ],
        work_units_by_job_id={
            "job-queued": (
                {
                    "status": "pending",
                    "available_at": datetime(2026, 5, 9, 11, 50, tzinfo=UTC),
                },
            ),
        },
        now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
    )

    self.assertEqual(operations.total_queue_depth, 1)
    self.assertEqual(operations.oldest_pending_age_seconds, 600.0)
```

- [ ] **Step 2: Добавить field и helpers**

В `OperationsOverview`:

```python
oldest_pending_age_seconds: float | None = None
```

Добавить helper, который считает pending work units и возраст самого старого `available_at`.

- [ ] **Step 3: Показать в Operations UI**

В `operations_body()` добавить metrics:

```python
("Queue depth", overview.total_queue_depth),
("Oldest pending", _duration(overview.oldest_pending_age_seconds)),
```

Не показывать raw document text, source snippets, prompt content или API key material.

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_live_monitor tests.test_admin_routes
```

Expected: OK.

## Task 8: Documentation and Deployment Checks

**Files:**

- Modify `README.md`
- Modify `README.project.md`
- Modify `docs/deployment/admin-vps-runbook.md`
- Modify `.env.server.example`

- [ ] **Step 1: Документировать модель лимитов**

Добавить в README/runbook короткое объяснение:

```markdown
Worker concurrency is bounded in layers: `TRANSLATION_MAX_PARALLEL_UNITS`
sets the process ceiling, provider key capacity narrows it, and scheduler
fairness caps prevent one user or one document from occupying all slots:
`SCHEDULER_MAX_ACTIVE_UNITS_PER_USER`,
`SCHEDULER_MAX_ACTIVE_JOBS_PER_USER`, and
`SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB`.
```

- [ ] **Step 2: Verify targeted suites**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_scheduler \
  tests.test_config \
  tests.test_worker \
  tests.test_persistent_jobs \
  tests.test_scheduler_runner \
  tests.test_postgres_scheduler \
  tests.test_admin_live_monitor \
  tests.test_admin_routes \
  tests.test_server_deployment_config
```

- [ ] **Step 3: Compile**

```bash
PYTHONPATH=src python3 -m compileall src
```

- [ ] **Step 4: Predeploy when environment allows**

```bash
scripts/predeploy_check.sh
```

Если Docker/Postgres недоступны локально, записать точную причину и приложить результаты targeted suites.

---

## Acceptance Criteria

- Capacity 1 остается serial legacy behavior.
- При нескольких users scheduler не дает одному user занять все слоты, если caps этого не разрешают.
- Один document/job не получает больше `SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB` active units.
- Worker global capacity пересекает configured scheduler global cap и effective provider capacity.
- PostgreSQL claim остается atomic, без duplicate claims.
- Stale completion защищен `claim_token`.
- Cancelled jobs не получают новые claims.
- Expired leases продолжают восстанавливаться существующим механизмом.
- Admin видит queue pressure, но не raw document text, prompt body, translated text или secrets.
- `.env.server.example` и runbook отражают новые beta-safe defaults.

## Почему Не Делаем Больше В Phase 1

Provider scoring и adaptive throttling лучше не вплетать в первый patch. Иначе при regression будет непонятно, сломались ли SQL fairness semantics, worker capacity math, key pool failover или adaptive feedback loop. Phase 1 должен дать стабильный scheduler foundation. После этого:

- Phase 2: key scoring/admin provider degradation visibility;
- Phase 3: adaptive throttling/ramp/circuit breaker;
- Phase 4: cost-aware scheduling and beta quotas.

Так мы получим production-safe throughput маленькими проверяемыми слоями, а не одним рискованным переписыванием scheduler/runtime.
