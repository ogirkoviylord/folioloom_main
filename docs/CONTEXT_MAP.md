# Context Map

## 1. Как пользоваться этой картой

Этот файл нужен AI-агентам перед началом задачи: он показывает, где искать контекст, какие части проекта связаны между собой и какие зоны нельзя менять без явного approve человека. Сначала сверяйтесь с `AGENTS.md`, затем с документами из раздела 2 и только после этого читайте код или тесты конкретной зоны.

## 2. Главные документы проекта

| Файл | Назначение | Когда читать |
|---|---|---|
| `AGENTS.md` | Правила работы в репозитории, запреты, формат отчета после задачи. | Перед любой задачей. |
| `docs/AGENT_SKILL_ROUTING.md` | Детальный справочник Skill Dispatch Contract: выбор роли, repo-level skill, supporting skills, approval evidence, state machine и stop-list. | Когда задача неоднозначная, multi-agent, risky, cross-role или требует выбора между repo-level и specialized skills. |
| `README.md` | Основной entrypoint: статус FolioLoom, supported/not supported, команды проверки, deployment overview. | Перед изменениями продукта, backend, bot, worker, deploy или тестов. |
| `README.project.md` | Project overview. | Когда нужен обзор проекта; сверять с `DOCUMENT_INDEX.md`. |
| `CURRENT_PROJECT_STATE.md` | Фактическое состояние проекта на restart, реализованные зоны и gaps. | Перед задачами про текущее состояние, roadmap, readiness или handoff. |
| `DOCUMENT_INDEX.md` | Индекс активных и historical docs; отделяет source of truth от архивных планов. | Перед чтением старых specs/plans. |
| `docs/PROJECT_BRIEF.md` | Продуктовый brief: аудитории, ценность, ограничения, компоненты, success criteria. | Перед продуктовыми и архитектурными задачами. |
| `docs/HANDOFF.md` | Текущий handoff: состояние, фокус, safe/risky tasks, последние изменения и вопросы владельцу. | Перед задачами по текущему состоянию, перед продолжением работы другим агентом и после завершенных изменений. |
| `docs/DECISIONS.md` | Журнал принятых и proposed решений; отделяет active decisions от TBD/Unknown. | Перед архитектурными, продуктовыми, релизными и рискованными задачами. |
| `docs/ROADMAP.md` | Рабочая очередь верхнего уровня для AI-оркестра: фазы, backlog candidates и правила scope. | Перед разбиением большой цели на issues и выбором следующей работы. |
| `docs/QUALITY_GATES.md` | Gate-ы качества для задач, code changes, docs changes, risky changes, PR и release. | Перед implementation/review и при выборе tests/checks. |
| `docs/RISK_REGISTER.md` | Реестр рисков: product, technical, security, privacy/legal, payment, operational и AI workflow. | Перед risky tasks, Architect review и release/readiness решениями. |
| `docs/RELEASE_CHECKLIST.md` | Checklist для documentation-only, internal, closed beta и future production release decisions. | Перед release, deploy, public launch или важным production change. |
| `docs/restart/folioloom-restart-spec.md` | Canonical restart-ТЗ и рамки продукта. | Перед крупными изменениями продукта, safety, payment или deployment. |
| `docs/restart/release-gates.md` | Gate A-D для stabilization, free beta, paid beta, public production. | Перед release/readiness задачами. |
| `docs/restart/two-week-engineering-plan.md` | Ближайший engineering plan. | Перед планированием следующей работы. |
| `docs/restart/real-file-test-matrix.md` | Real-file corpus и QA matrix для TXT/DOCX/EPUB. | Перед задачами про качество файлов, fixtures и release evidence. |
| `docs/restart/upload-safety-and-retention.md` | Upload hardening, quarantine, local malware scanning, TTL и retention rules. | Перед задачами про загрузки, malware scanning, хранение, удаление и user data. |
| `docs/deployment/admin-vps-runbook.md` | VPS/admin/tunnel deployment model. | Перед ops/deployment/admin access задачами. |
| `docs/deployment/restore-runbook.md` | Backup verification и restore rehearsal. | Перед backup/restore задачами. |
| `docs/deployment/server-beta.md` | Historical/superseded deployment note. | Читать только как архив, если активные runbooks не отвечают на вопрос. |
| `docs/superpowers/specs/` | Specs по admin, scheduler, provider, quality, pricing draft и другим зонам. | Читать точечный spec для соответствующей зоны. |
| `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md` | Design-only owner-only glossary/profile diagnostic sidecar schema, raw-field manifest, access/export boundaries and implementation gates. | Перед #412 follow-ups, #413 provider spike planning, glossary/profile diagnostic storage/admin/archive work. |
| `docs/superpowers/specs/2026-06-12-deepseek-pro-glossary-profile-spike-report.md` | Metadata-only #413 bounded DeepSeek Pro glossary/profile spike report with validation outcomes, token overrun evidence and recommendation not to integrate runtime roles yet. | Перед follow-up provider/glossary prompt design, any further #413-style live spike, runtime integration review or glossary diagnostics planning. |
| `docs/superpowers/specs/2026-06-12-chunked-deepseek-pro-glossary-editor-spike-report.md` | Metadata-only #416 bounded chunked DeepSeek Pro glossary-editor spike report with validation outcomes, merge findings, token/latency shape and pivot-before-runtime recommendation. | Перед follow-up chunked glossary editor prompt design, further live spike planning, runtime integration review or glossary diagnostics planning. |
| `docs/superpowers/plans/` | Архив implementation plans; многие планы уже реализованы или superseded. | Читать только после `DOCUMENT_INDEX.md`; не считать unchecked items roadmap без подтверждения. |

## 3. Карта директорий

| Путь | Что внутри | Кто должен читать | Риск изменений |
|---|---|---|---|
| `.` | Корневые docs, env examples, real `.env*`, Dockerfile, compose, pyproject. | Все агенты. | human approval required для `.env*`, deploy, deps и конфигов. |
| `.agents/skills/` | Repo-level skill instructions for Idea Intake, Orchestrator, Architect, Implementer, Reviewer, Scribe and Release Readiness roles. | Все агенты при выборе или применении роли. | medium; keep aligned with `AGENTS.md` and `docs/AGENT_SKILL_ROUTING.md`. |
| `docs/` | Project docs, restart docs, deployment runbooks, specs/plans archive. | Scribe, Orchestrator, Architect, Reviewer. | medium; high для deployment, release gates, legal/privacy/safety текста. |
| `src/translator_service/` | Основной Python package: backend, bot, worker, translation core, persistence, safety. | Implementer, Architect, Reviewer. | medium/high по зоне. |
| `src/translator_service/admin/` | FastAPI admin console: auth, settings, secrets, provider keys, costs, audit, live, operations, owner-only text diagnostics and run-log reader. | Admin/backend agents. | human approval required для auth, secrets, security, provider keys, user data and any raw-text diagnostic expansion. |
| `src/translator_service/bot/` | aiogram Telegram runtime, messages, activity phrases. | Bot/UI agents. | high; затрагивает UX, Telegram API, user data, payments-adjacent flows. |
| `src/translator_service/format_adapters/` | TXT/DOCX/EPUB adapters, contracts, EPUB repair, TXT layout. | Translation/file-format agents. | medium/high; file parsing and output fidelity. |
| `src/translator_service/glossary_contracts.py` | Local glossary schema dataclasses, enums, validators and compact signature helpers for the glossary epic. | Implementer, Architect, Reviewer for glossary issues. | medium/high; contract changes can affect future prompt/cache/provider/runtime integrations, but this module has no provider/storage/runtime side effects by itself. |
| `src/translator_service/glossary_scanner.py` | Local deterministic glossary candidate/evidence scanner over existing TXT/DOCX/EPUB adapter plans. | Implementer, Architect, Reviewer for glossary issues. | medium/high; scanner output can affect future prompt budgets and glossary quality, but this module has no provider/storage/runtime side effects by itself. |
| `src/translator_service/book_profile.py` | Local deterministic book translation profile detector, profile contract validator and profile-specific glossary rule data for the glossary epic. | Implementer, Architect, Reviewer for glossary/profile issues. | medium/high; profile/rule output can affect future prompts/cache/provider/runtime diagnostics, but this module has no provider/storage/runtime side effects by itself. |
| `src/translator_service/glossary_role_validators.py` | Local fake-output JSON validators for approved DeepSeek Pro glossary/profile roles and cross-role disagreement checks. | Implementer, Architect, Reviewer for glossary/provider-boundary issues. | medium/high; role outputs are untrusted model output and can affect future snapshots, but this module has no provider/runtime/prompt/diagnostic side effects by itself. |
| `src/translator_service/translation_contract_snapshot.py` | Local deterministic translation contract snapshot builder for glossary/profile planning metadata. | Implementer, Architect, Reviewer for glossary snapshot/cache/diagnostics issues. | medium/high; snapshots are user-data-adjacent contract metadata and can affect future cache/diagnostics/prompt integration, but this module has no provider/runtime/cache/storage side effects by itself. |
| `src/translator_service/glossary_selection.py` | Local deterministic per-work-unit glossary subset selector with prompt-budget metadata. | Implementer, Architect, Reviewer for glossary selection/prompt-budget issues. | medium/high; selection can affect future prompts, cost and diagnostics, but this module has no provider/runtime/prompt/cache/storage side effects by itself. |
| `src/translator_service/glossary_editor_packets.py` | Local deterministic DeepSeek Pro glossary-editor packet contract and packet builder with stable ids/signatures, compact reference payloads, budget reservation and degradation metadata. | Implementer, Architect, Reviewer for chunked glossary-editor issues. | medium/high; packets can affect future provider prompts and diagnostics, but this module has no provider/runtime/prompt/cache/storage side effects by itself. |
| `src/translator_service/glossary_editor_chunk_outputs.py` | Local fake-output validators and deterministic merge/adjudication contract for chunked glossary-editor packet outputs. | Implementer, Architect, Reviewer for chunked glossary-editor validator and provider-boundary issues. | medium/high; validators shape future provider output handling and conflict policy, but this module has no provider/runtime/prompt/cache/storage side effects by itself. |
| `src/translator_service/translation_policy.py` | Translation prompt policy, output-contract policy and optional compact glossary/profile signature context for future cache/prompt-safe integration. | Implementer, Architect, Reviewer for translation policy, provider-boundary and glossary cache-signature issues. | medium/high; policy signatures can affect cache reuse and future prompt behavior. #411 adds signatures only and does not inject glossary/profile data into prompts. |
| `src/translator_service/translation_cache.py` | In-memory translation cache key builder for repeated DOCX/EPUB translation units. | Implementer, Architect, Reviewer for cache/policy-signature work. | medium/high; cache-key changes can affect stale reuse, cost and latency. Glossary/profile signature context is optional and compact; migration/stale-cache behavior remains `TBD`. |
| `tests/` | Unit/regression tests for admin, bot, scheduler, worker, provider, translation, deployment smoke. | Reviewer, QA, Implementer. | low/medium; high если меняются safety/payment/auth expectations. |
| `scripts/` | Deploy, predeploy, server smoke/status, backup/verify, sample generation, security summary. | Ops, Reviewer, Implementer for scripts only. | human approval required for deploy/backup/server scripts. |
| `.github/` | GitHub issue templates, PR template and `workflows/checks.yml`. | CI / GitHub workflow agents. | low/medium; do not add deploy, secrets, production operations or required-approval gates without owner approval. |
| `database/`, `db/`, `migrations/` | Not found as project directories. | Database agents. | human approval required if created or changed. |
| `var/` | Runtime sqlite DBs, object storage, translation run artifacts. | Ops/debug agents only. | human approval required; likely user/runtime data. |
| `artifacts/`, `epub_audit_output/`, `test_samples/` | Sample/output files and real-file fixtures. | QA/file-format agents. | medium; high if copyrighted/user data risk. |
| `tools/` | Utility tooling, currently EPUB audit helper. | QA/tooling agents. | medium. |
| `tools/deepseek_glossary_profile_spike.py` | Standalone #413 bounded fixture spike runner for local/fake and approved live DeepSeek Pro glossary/profile role validation. | Glossary/provider spike agents only after exact owner approval. | high for live mode; can send fixture excerpts to provider and write owner-only raw diagnostics under approved untracked output directories. |
| `tools/deepseek_chunked_glossary_editor_spike.py` | Standalone #416 bounded chunked glossary-editor spike runner for fake preflight and owner-approved live DeepSeek-compatible calls over the first READY packet per approved fixture. | Glossary/provider spike agents only after #414/#415 and exact owner approval. | high for live mode; can send bounded fixture excerpts to provider and write owner-only raw diagnostics under approved untracked output directories. |
| `handoff/` | Restart package archive and copied configs. | Orchestrator/Scribe. | medium; may contain stale or bundled context. |
| `.superpowers/` | Local skill/process state. | Usually not needed. | low; avoid unrelated edits. |
| `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `.DS_Store` | Generated/cache files. | Usually no one. | low; do not treat as source of truth. |

## 4. Основные зоны продукта

### Backend

- Пути: `src/translator_service/api.py`, `src/translator_service/config.py`, core modules in `src/translator_service/`.
- Назначение: FastAPI health/admin app, configuration, document/job/order/user/state services, provider runtime integration.
- Важные файлы: `api.py`, `config.py`, `documents.py`, `orders.py`, `users.py`, `file_storage.py`, `deepseek_client.py`, `ai_provider_runtime.py`, `deepseek_key_pool.py`, `beta_safety.py`, `security_telemetry.py`.
- Связанные тесты: `tests/test_api.py`, `tests/test_config.py`, `tests/test_documents.py`, `tests/test_orders.py`, `tests/test_users.py`, `tests/test_file_storage.py`, `tests/test_ai_provider_runtime.py`, `tests/test_deepseek_*`, `tests/test_beta_safety*`, `tests/test_security_*`.

### Bot / UI

- Пути: `src/translator_service/bot/`, `src/translator_service/bot_translation_service.py`.
- Назначение: Telegram-first UX: upload, language, estimate, rights confirmation, progress, cancel/status/history flows.
- Важные файлы: `bot/runtime.py`, `bot/messages.py`, `bot/activity_phrases.py`, `bot/__main__.py`, `bot_translation_service.py`.
- Связанные тесты: `tests/test_bot_runtime.py`, `tests/test_bot_runtime_logging.py`, `tests/test_bot_messages.py`, `tests/test_bot_translation_service.py`.

### Frontend

- Not found as separate web frontend directory.
- Admin UI appears server-rendered/route-based under `src/translator_service/admin/`.

### Admin

- Пути: `src/translator_service/admin/`.
- Назначение: SSH-tunneled owner/admin console: login/session auth, settings, allowlist, encrypted secrets, provider keys/health/probe/runtime, costs, live monitor, operations, audit, quality, deployment smoke.
- Важные файлы: `routes.py`, `views.py`, `auth.py`, `rbac.py`, `secrets.py`, `secret_safety.py`, `settings.py`, `ai_provider_keys.py`, `provider_*`, `costs.py`, `live.py`, `operations.py`, `audit.py`, `deployment_smoke.py`.
- Связанные тесты: `tests/test_admin_*.py`, `tests/test_server_deployment_config.py`.

### Worker / background jobs

- Пути: `src/translator_service/worker.py`, `scheduler.py`, `scheduler_runner.py`, `postgres_scheduler.py`, `persistent_jobs.py`, `persistent_job_store.py`, `job_runner.py`, `persistent_planner.py`, `persistent_assembly.py`.
- Назначение: persistent jobs/work units, leases, retries, worker loop, scheduler fairness/capacity, partial/final assembly.
- Важные файлы: listed above plus `translation_jobs.py`, `translation_runner.py`, `translation_run_logs.py`, `translation_metrics.py`.
- Связанные тесты: `tests/test_worker.py`, `tests/test_scheduler*.py`, `tests/test_postgres_scheduler.py`, `tests/test_persistent_*`, `tests/test_job_runner.py`, `tests/test_translation_*`.

### Database / migrations

- Пути: no dedicated migrations directory found.
- Назначение: PostgreSQL scheduler state through `postgres_scheduler.py`; SQLite fallback/runtime stores through `persistent_job_store.py`, `beta_safety_store.py` and admin/runtime DB paths.
- Risk level: human approval required.
- Human approval requirements: any schema/state migration, persistent data handling, `var/*.sqlite3`, PostgreSQL model changes, backup/restore behavior, retention/TTL behavior, or new database directory requires explicit human approval.

### Tests

- Где лежат: `tests/`.
- Как устроены: Python unittest/pytest-compatible test files grouped by module/feature; README verification uses `PYTHONPATH=src python3 -m unittest discover -s tests`, compileall, and `scripts/predeploy_check.sh`.
- Какие зоны покрыты: admin, bot, worker, scheduler/Postgres scheduler, provider layer, translation pipeline, format adapters, safety/security telemetry, deployment smoke, backup scripts.
- Какие зоны не покрыты: Unknown from this mapping task. Docs mention remaining release gaps for real-file matrix, DOCX visual/openability QA, EPUBCheck/equivalent, cancel/resume/restart validation, restore rehearsal artifacts and server smoke evidence.

### CI / GitHub Actions

- Workflows found: `.github/workflows/checks.yml`.
- Что проверяют: on pull requests and pushes to `main`, GitHub Actions checks out the repo, sets up Python 3.13, installs the project with `python -m pip install -e .`, runs `PYTHONPATH=src python -m compileall src`, and runs `PYTHONPATH=src python -m unittest discover -s tests`.
- Что не проверяют: deploy, server smoke, secrets, real `.env*`, backup/restore rehearsal, real-file release matrix, typecheck and formatting. Current GitHub run status is Unknown unless inspected on the PR/checks page.

### Deployment / infrastructure

- Файлы: `Dockerfile`, `docker-compose.yml`, `.env.server.example`, `scripts/deploy_server.sh`, `scripts/predeploy_check.sh`, `scripts/server_smoke_check.sh`, `scripts/server_status.sh`, `scripts/backup_server_data.py`, `scripts/verify_backup_export.py`, `docs/deployment/`.
- Назначение: VPS Docker Compose stack with `api`, `bot`, `worker`, `postgres`, `redis`; SSH-tunneled admin; backup/restore workflow.
- Почему high-risk: deployment touches secrets, server state, runtime data, public exposure, backups, restore, provider keys and production-like availability. Production deployment requires explicit human approval.

## 5. Где агентам искать информацию перед задачей

- Перед любой задачей читать `AGENTS.md`.
- Перед продуктовой задачей читать `docs/PROJECT_BRIEF.md` и `docs/restart/two-week-engineering-plan.md`; если появится `docs/ROADMAP.md`, читать и его.
- Перед задачей по текущему состоянию читать `CURRENT_PROJECT_STATE.md`; если появится `docs/HANDOFF.md`, читать и его.
- Перед архитектурной задачей читать `docs/restart/folioloom-restart-spec.md`, relevant specs in `docs/superpowers/specs/`; если появится `docs/DECISIONS.md`, читать и его.
- Перед релизной задачей читать `docs/restart/release-gates.md`; если появится `docs/RELEASE_CHECKLIST.md`, читать и его.
- Перед рискованной задачей читать `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `docs/restart/release-gates.md`; если появятся `docs/RISK_REGISTER.md` и `docs/QUALITY_GATES.md`, читать их.
- Перед чтением старых plans/specs читать `DOCUMENT_INDEX.md`.

## 6. Зоны, требующие approve человека

- `.env`, `.env.dev`, `.env.beta` и любые `.env*`: secrets/env, provider keys, Telegram/admin/Postgres settings.
- `Dockerfile`, `docker-compose.yml`, `.env.server.example`, `scripts/deploy_server.sh`, `scripts/server_*`, `scripts/predeploy_check.sh`, `docs/deployment/`: deployment/infrastructure.
- `scripts/backup_server_data.py`, `scripts/verify_backup_export.py`, `var/`, object storage paths, sqlite/runtime DBs: user data, backups, restore and retention.
- Any database schema/state layer: `postgres_scheduler.py`, `persistent_job_store.py`, `beta_safety_store.py`, new migrations or DB directories.
- Payment/pricing/order zones: `pricing.py`, `billing.py`, `orders.py`, `order_estimates.py`, `order_payments.py`, payment/pricing docs/specs. Paid beta is gated.
- Auth/security/secrets zones: `src/translator_service/admin/auth.py`, `rbac.py`, `secrets.py`, `secret_safety.py`, `security_telemetry.py`, `security_summary.py`, admin session/secret settings.
- Legal/privacy/user-data handling: upload safety/retention docs, file storage,
  user activity, raw document handling, rights confirmation, logs/admin display
  of document text and the approved owner-only raw diagnostic surfaces.
- External API integrations: Telegram bot runtime, DeepSeek client/key pool/provider runtime, provider validation/probe/balance/key management.
- Destructive operations: deleting runtime data, changing retention/TTL, modifying backup/restore, force-resetting git, removing artifacts unless explicitly approved.

## 7. Потенциальные конфликтные зоны для параллельных агентов

- Нельзя параллельно менять `persistent_jobs`/scheduler/Postgres state и worker claim/cancellation logic без координации: это один state machine.
- Нельзя параллельно менять bot flow и backend job/order contract без общего API/contract plan.
- Нельзя параллельно менять provider key selection/throttling и admin provider health/runtime UI без согласования telemetry fields.
- Нельзя параллельно менять pricing/payment/order estimates и bot confirmation/payment-adjacent UX без owner approval и gate context.
- Нельзя параллельно менять file adapters, persistent assembly и real-file tests для одного формата без согласования expected output contracts.
- Нельзя параллельно менять auth/RBAC/secrets и admin routes/views: высокий риск ослабить доступ или redaction.
- Нельзя параллельно менять deployment scripts, compose/env contract и server runbooks без единого Reviewer/Architect pass.
- Нельзя параллельно менять retention/TTL/upload safety и backup/restore/runtime storage без data-handling decision.

## 8. Быстрые маршруты для типовых задач

### Если задача про bugfix

Читать:
- `AGENTS.md`
- `CURRENT_PROJECT_STATE.md`
- модуль и ближайшие тесты по имени файла/фичи

Проверять:
- targeted unit tests for touched zone
- `PYTHONPATH=src python3 -m compileall src` для code changes

### Если задача про новую функцию

Читать:
- `AGENTS.md`
- `docs/PROJECT_BRIEF.md`
- `docs/restart/folioloom-restart-spec.md`
- `docs/restart/release-gates.md`
- relevant spec/plan from `DOCUMENT_INDEX.md`

Проверять:
- focused tests for new behavior
- related safety/privacy/deployment/payment gates

### Если задача про тесты

Читать:
- `AGENTS.md`
- target module
- related existing `tests/test_*.py`
- `README.md` verification commands

Проверять:
- new/changed targeted tests
- avoid weakening existing assertions around safety, auth, payments, secrets and user data

### Если задача про релиз

Читать:
- `AGENTS.md`
- `README.md`
- `CURRENT_PROJECT_STATE.md`
- `DOCUMENT_INDEX.md`
- `docs/restart/release-gates.md`
- `docs/deployment/admin-vps-runbook.md`
- `docs/deployment/restore-runbook.md`

Проверять:
- common verification commands from release gates
- `scripts/predeploy_check.sh`
- server smoke/backup/restore evidence only with human-approved environment access

### Если задача про документацию

Читать:
- `AGENTS.md`
- `README.md`
- `DOCUMENT_INDEX.md`
- relevant existing docs under `docs/`
- relevant project files if documenting code behavior

Проверять:
- facts are confirmed by repo files
- use `TBD` for human decisions and `Unknown` where evidence is missing
- do not weaken safety, legal, privacy, security, payment or deployment guardrails
