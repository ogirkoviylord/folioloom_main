# FolioLoom Current Project State

Актуальный источник фактического состояния проекта на 2026-05-10.

## Коротко

FolioLoom - это рабочая foundation для closed beta Telegram-first сервиса
перевода авторизованных длинных документов. Проект уже вышел за рамки
in-memory prototype: есть persistent jobs/work units, object storage,
worker loop, admin console, Docker Compose deployment и backup/restore
workflow.

FolioLoom пока не является paid public production service. Ближайшая цель -
free closed beta после прохождения release gates.

## Текущий стек

- Python 3.13.
- aiogram Telegram runtime.
- FastAPI API/admin app.
- Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- PostgreSQL scheduler storage для server runtime.
- SQLite fallback/runtime stores там, где это явно настроено.
- Local object storage через host `./var`, смонтированный в containers как
  `/app/var` и `/data`.
- DeepSeek-compatible chat completion providers как внутренний provider layer.
- TXT/DOCX/EPUB planners, adapters и assembly.

## Последняя зафиксированная проверка

После Phase 3 adaptive provider throttling были пройдены:

```bash
PYTHONPATH=src python3 -m unittest tests.test_provider_throttle tests.test_deepseek_key_pool tests.test_ai_provider_runtime tests.test_bot_runtime tests.test_scheduler_runner tests.test_admin_provider_health tests.test_admin_routes tests.test_admin_live_monitor tests.test_server_deployment_config
```

Результат: Phase 3 targeted suite `Ran 176 tests`, `OK`; scheduler regression
`Ran 88 tests`, `OK`, `skipped=13`; Docker/Postgres scheduler `Ran 14 tests`,
`OK`; predeploy check passed.

После Phase 1 smart scheduler fairness/capacity и Phase 2 provider channel
observability были пройдены:

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool tests.test_ai_provider_runtime tests.test_bot_runtime tests.test_admin_provider_health tests.test_admin_routes tests.test_admin_live_monitor tests.test_server_deployment_config
PYTHONPATH=src python3 -m unittest tests.test_worker tests.test_scheduler tests.test_scheduler_runner tests.test_persistent_jobs tests.test_postgres_scheduler
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
docker compose run --rm --no-deps -v "$PWD:/workspace" -w /workspace -e TEST_POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator -e PYTHONPATH=src api python -m unittest tests.test_postgres_scheduler
```

Результаты: Phase 2 targeted suite `Ran 146 tests`, `OK`; scheduler regression
`Ran 85 tests`, `OK`, `skipped=13`; Docker/Postgres scheduler `Ran 14 tests`,
`OK`; predeploy check passed.

После добавления rights confirmation gate были пройдены:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Результат последнего полного unittest suite: `Ran 856 tests`, `OK`,
`skipped=10`.

После добавления DeepSeek balance и фикса совместной работы admin/env ключей
были пройдены targeted checks:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance tests.test_admin_bootstrap_config tests.test_deepseek_key_sources tests.test_bot_runtime tests.test_server_deployment_config
scripts/predeploy_check.sh
```

Результат targeted suite: `Ran 71 tests`, `OK`.

Важная оговорка: repo-wide `python3 -m ruff check --no-cache src tests scripts`
пока не является release blocker. Он падает на исторических style/import/line
length issues. Текущий gate - targeted lint внутри `scripts/predeploy_check.sh`.

## Что реализовано

### Bot and user flow

- aiogram runtime.
- `/start`, menu/help/language flows.
- Upload/estimate/confirm/progress/cancel/status/history-oriented flows.
- Invite-only beta allowlist by Telegram user id, editable from admin settings
  with per-ID add/remove controls and an explicit admin on/off toggle. The
  toggle defaults off, so the bot remains open until the owner enables
  enforcement.
- Rights confirmation gate after document upload/validation and before target
  language/estimate/full processing. Confirmation stores safe metadata only:
  boolean, timestamp, version and source.
- TXT/DOCX/EPUB upload and translation path.
- Cooperative cancellation with partial output.
- My Books/history foundations: ownership checks, download, resume/cancel
  affordances и delete confirmation.
- UI localization: Russian, Ukrainian, French, Spanish, English, Dutch.

### Translation core

- TXT, DOCX, EPUB extraction/planning/assembly.
- Separate format adapters for TXT/DOCX/EPUB.
- Persistent planners and persistent assembly for final and partial outputs.
- DOCX support includes tables/pseudo-tables, headers, footers, footnotes,
  endnotes, comments, hyperlinks, basic run formatting, hidden text,
  subscript/superscript and protected structured text.
- EPUB support includes spine order, XHTML text blocks, inline formatting,
  note/footnote anchors, OPF/NCX auxiliary text and repair helpers.
- Output contract checks and repair path for unsafe provider outputs.
- Russian and Ukrainian quality/profile foundations.

### Backend, persistence and worker

- Local object storage for source, intermediate, partial and final files.
- SQLite persistent job/work-unit store for local/fallback paths.
- PostgreSQL scheduler store for server runtime.
- Scheduler runner and worker loop.
- Work-unit leases, retries, attempts, usage accounting, worker heartbeats,
  partial/final output keys.
- Worker-side scheduler execution can run multiple distinct scheduled work
  units concurrently within configured capacity, while provider calls remain
  capped by DeepSeek key/channel capacity.
- Scheduler claim ordering is beta-safe and fairness-aware: user/job/document
  active caps, priority aging and capacity-aware batch claiming prevent one
  huge document or heavy user from monopolizing worker slots.
- Docker Compose stack with `api`, `bot`, `worker`, `postgres`, `redis`.
- Server env example uses `SCHEDULER_BACKEND=postgres`.

### Provider layer

- DeepSeek-compatible chat completion client.
- Multiple internal API channel/key support.
- Weighted least-loaded key selection with active-load, fairness, recent-error
  and latency signals.
- Key cooldown/failover behavior for rate-limit/unavailable/timeout failures.
- Local per-worker adaptive provider throttling with conservative initial
  capacity, success-based ramp, multiplicative decrease and provider circuit
  breaker for sustained provider degradation or auth/billing failures.
- Admin-visible provider runtime status, reload request flow and per-channel
  health telemetry.
- Runtime channel telemetry includes active requests, capacity, cooldown,
  latency, 429/503/timeout/malformed/auth/billing counters and redacted safe
  error summaries.
- Runtime provider telemetry includes adaptive limit, available provider slots,
  circuit state, reset remaining time and redacted last reason.
- Provider validation/probe surfaces.
- Admin-visible DeepSeek account balance snapshot/refresh flow.
- DeepSeek admin keys and `.env` keys are additive for balance/runtime use.

### Admin console

Implemented owner/admin areas include:

- owner login/session auth;
- RBAC-shaped model;
- settings;
- encrypted secret storage;
- integration registry and connection rows;
- AI provider keys;
- DeepSeek account balance snapshot/refresh;
- provider validation/probe/runtime status/reload;
- overview action center;
- live monitor;
- translation run logs and detail/download;
- user activity;
- user list/details;
- security events;
- operations/jobs;
- token/cost analytics;
- quality run trigger;
- audit logging;
- deployment smoke checks.
- closed-beta allowlist settings, per-ID add/remove controls and enforcement
  toggle.

Admin access is SSH-tunnel-only for closed beta. It is not a public admin
product yet.

### Deployment and operations

- `docker-compose.yml`.
- `.env.server.example`.
- `scripts/deploy_server.sh`.
- `scripts/predeploy_check.sh`.
- `scripts/server_smoke_check.sh`.
- `scripts/server_status.sh`.
- `scripts/backup_server_data.py`.
- `scripts/verify_backup_export.py`.
- VPS runbook and restore runbook under `docs/deployment/`.

## Main gaps against closed beta

- Per-user quotas, global cost cap and admin kill switch.
- Free preview before full translation.
- Upload hardening/quarantine baseline.
- TTL cleanup/delete verification.
- Real-file TXT/DOCX/EPUB matrix and release report.
- EPUBCheck or equivalent release validation.
- DOCX openability/visual QA.
- Alerts MVP.
- Backups visibility page.
- Scheduler/runtime consistency smoke as a release artifact.

## Paid beta blockers

Paid beta is blocked until Telegram Stars/XTR flow, `pre_checkout_query`,
`successful_payment`, stored `telegram_payment_charge_id`, idempotency,
persistent ledger, reservation/capture/refund, `/paysupport`, reconciliation
and support/refund policy are implemented and tested.

## Recommended restart decision

Run free closed beta first. The engineering foundation is strong enough to test
with trusted users and real authorized documents, but quality, reliability,
rights flow, upload safety, TTL, backups visibility and payment readiness still
need gates before paid/public launch.
