# Project Brief

## 1. Краткое описание проекта

FolioLoom - это Telegram-first сервис для перевода авторизованных длинных документов: книг, глав, рукописей, редакторских материалов, public-domain текстов и документов, на которые у пользователя есть права. Основная проблема проекта - дать пользователю понятный путь от загрузки TXT/DOCX/EPUB до готового переведенного файла с прогрессом, отменой, частичным результатом и историей. Основной пользователь сейчас - доверенный участник будущей free closed beta, который загружает документ в Telegram и получает перевод через внутренний DeepSeek-compatible provider layer. Владелец/оператор управляет beta-доступом, лимитами, ключами провайдера, состоянием задач и диагностикой через SSH-tunneled admin console. Проект пока не является публичным production-сервисом или платным SaaS.

## 2. Целевая аудитория

### Доверенные beta-пользователи

- Кто это: пользователи из invite-only cohort, идентифицируемые по Telegram ID.
- Зачем им продукт: переводить свои или разрешенные длинные документы в поддерживаемых форматах TXT, DOCX и EPUB.
- Ограничения и ожидания: должны подтверждать права на документ; ожидают понятный Telegram-flow, оценку, прогресс, отмену, частичный или финальный результат; должны принимать ограничения closed beta по форматам, лимитам и доступности.

### Владелец/оператор сервиса

- Кто это: owner/admin проекта.
- Зачем им продукт: запускать и контролировать закрытую beta, управлять allowlist, лимитами, kill switch, DeepSeek-ключами, диагностикой, бэкапами и release gates.
- Ограничения и ожидания: admin должен оставаться SSH-tunnel-only; секреты и raw document text не должны показываться в админке или логах; deployment и payment/readiness gates требуют ручного контроля.

### Будущие платные пользователи

- Кто это: TBD. Репозиторий описывает paid beta как будущую стадию, но не фиксирует конкретные сегменты.
- Зачем им продукт: Assumption - получать более надежный перевод длинных документов внутри Telegram после появления безопасного платежного потока.
- Ограничения и ожидания: paid beta заблокирована до Telegram Stars/XTR flow, payment ledger, refund/support path, reconciliation и support/refund policy.

## 3. Главная ценность продукта

Подтвержденная ценность FolioLoom - перевод длинных документов прямо из Telegram с сохранением структуры и управляемым backend-процессом. Проект делает упор не на одноразовый prompt, а на durable workflow: accepted documents, jobs, work units, partial/final results, object storage, worker loop и админскую наблюдаемость. Ключевые функции: upload/validation для TXT/DOCX/EPUB, выбор языка, rights confirmation, estimate/confirmation, progress/cancel/status/history, My Books/history, persistent jobs/work units, worker execution, beta allowlist, cost caps, admin kill switch, DeepSeek-compatible provider layer и backup/restore workflow. Для beta важна не публичная монетизация, а проверка качества, надежности и безопасности на реальных авторизованных документах.

## 4. Текущая стадия проекта

Стадия: active development / working closed-beta foundation.

Репозиторий прямо указывает, что проект уже не in-memory prototype: реализованы persistent jobs/work units, local object storage, worker loop, FastAPI admin console, Docker Compose deployment, backup/restore workflow и широкий unittest suite. Следующий milestone - free closed beta. Public production не готов, paid launch заблокирован отдельным payment/readiness gate.

Уже реализовано:

- Telegram bot runtime на aiogram с upload/estimate/confirm/progress/cancel/status/history-oriented flows.
- TXT/DOCX/EPUB adapters, planners, assembly и quality/profile foundations для русского и украинского.
- Backend foundation: persistent job/work-unit store, PostgreSQL scheduler store для server runtime, local object storage, worker loop.
- Admin console: owner auth, settings, allowlist, provider keys/health, operations, live monitor, costs, audit/security surfaces и deployment smoke checks.
- Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- Backup/restore scripts и deployment runbooks.

Выглядит незавершенным:

- Free preview before full translation.
- Upload hardening/quarantine baseline, including the planned local malware/AV
  scanning gate accepted by the owner on 2026-05-22.
- TTL cleanup/delete verification.
- Real-file TXT/DOCX/EPUB release matrix and report.
- EPUBCheck or equivalent validation.
- DOCX openability/visual QA.
- Alerts MVP and Backups visibility page.
- Paid beta payment flow and ledger.

Где нужны решения владельца проекта:

- Go/no-go для free closed beta после release gates.
- Политика платного запуска, refund/support и reconciliation.
- Юридические/privacy/AUP документы перед public production.
- Решение по публичному admin hardening, offsite backups, support workflow и incident runbooks.

## 5. Основные пользовательские сценарии

### Сценарий: перевод документа в Telegram

- Пользователь: доверенный beta-пользователь.
- Шаги: открыть бота, выбрать язык интерфейса, загрузить TXT/DOCX/EPUB, пройти validation, подтвердить права, выбрать целевой язык, получить estimate, подтвердить перевод, отслеживать progress, получить финальный или частичный файл.
- Ожидаемый результат: пользователь получает переведенный документ или безопасное сообщение об ошибке/частичный результат.
- Текущая готовность: partial. Основной flow реализован, но release matrix,
  upload hardening including local malware/AV scanning, и TTL остаются gap.

### Сценарий: отмена или продолжение работы

- Пользователь: beta-пользователь.
- Шаги: во время перевода нажать cancel или открыть history/My Books, посмотреть статус, скачать результат, продолжить/отменить доступные задачи или удалить книгу.
- Ожидаемый результат: отмена кооперативно останавливает работу после текущего фрагмента, сохраняет доступный partial output, история показывает доступные файлы.
- Текущая готовность: partial. В репозитории есть cancellation, partial output, My Books/history foundations, но release gates требуют cancel/resume/restart validation.

### Сценарий: управление closed beta

- Пользователь: owner/admin.
- Шаги: открыть admin через SSH tunnel, войти, настроить allowlist, включить enforcement, проверить Costs/Settings/Live, при необходимости включить kill switch.
- Ожидаемый результат: beta-доступ и нагрузка ограничены, новые uploads/jobs блокируются при паузе или превышении caps.
- Текущая готовность: confirmed для основных admin allowlist/cost/kill-switch функций; partial для полного release readiness.

### Сценарий: эксплуатация и восстановление

- Пользователь: owner/operator.
- Шаги: deploy через `scripts/deploy_server.sh`, проверить `scripts/server_smoke_check.sh` и `scripts/server_status.sh`, создать backup, проверить manifest, выполнить restore rehearsal по runbook.
- Ожидаемый результат: Docker Compose stack работает, данные можно проверить и восстановить по документированной процедуре.
- Текущая готовность: partial. Скрипты и runbooks есть, но release gates требуют backup visibility, restore rehearsal и серверные smoke artifacts.

## 6. Основные компоненты продукта

| Компонент | Назначение | Где находится | Готовность | Риски/неясности |
| --- | --- | --- | --- | --- |
| Backend/API | Health endpoint и FastAPI admin router | `src/translator_service/api.py`, `src/translator_service/admin/` | partial/confirmed foundation | Admin не должен становиться публичным до hardening. |
| Telegram bot | Пользовательский Telegram-flow | `src/translator_service/bot/`, `src/translator_service/bot_translation_service.py` | partial | Нужны release checks для preview, resume/restart и real files. |
| Worker | Выполнение persistent work units | `src/translator_service/worker.py`, `src/translator_service/scheduler_runner.py` | partial | Требуется подтверждать scheduler/runtime consistency на сервере. |
| Translation core | Extraction, planning, translation, assembly, policy, quality checks | `src/translator_service/format_adapters/`, `translation_runner.py`, `persistent_planner.py`, `persistent_assembly.py`, quality/profile modules | partial | DOCX/EPUB fidelity требует openability/visual/EPUBCheck gates. |
| Database/state | PostgreSQL scheduler state, SQLite fallback/runtime stores | `docker-compose.yml`, `persistent_jobs.py`, `persistent_job_store.py`, `postgres_scheduler.py` | partial | Production correctness должна опираться на Postgres; SQLite paths остаются fallback/runtime. |
| Storage | Local object storage for source/intermediate/partial/final files | `src/translator_service/file_storage.py`, host `./var`, container `/data` | partial | TTL cleanup/delete verification остается gap. |
| Admin console | Owner operations, settings, allowlist, provider health, costs, logs, audit | `src/translator_service/admin/` | partial | Alerts MVP и Backups visibility еще нужны. |
| External APIs | DeepSeek-compatible chat completion providers; Telegram Bot API | `deepseek_client.py`, `deepseek_key_pool.py`, `ai_provider_runtime.py`, bot runtime | partial | Provider failures, auth/billing failures and balance must stay diagnosable without leaking secrets/text. |
| Tests | Unit/regression suite | `tests/`, `test_samples/` | confirmed broad coverage | Последний полный passing status подтвержден документацией, не текущим запуском в этой задаче. |
| CI | minimal workflow present / current run status Unknown | `.github/workflows/checks.yml` | partial | Workflow runs compile and unit tests on PRs and pushes to `main`, but this task did not verify any GitHub run status. |
| Deployment | Docker Compose VPS model | `Dockerfile`, `docker-compose.yml`, `scripts/deploy_server.sh`, `docs/deployment/` | partial | Production deployment требует human approval; public production не готов. |

## 7. Неприкосновенные ограничения

- Не менять secrets, `.env` files, deployment, payments, pricing, auth, security, legal/privacy text, user data handling или database migrations без явного human approval.
- Не выполнять production deployment без явного human approval.
- Не добавлять production dependencies без явного human approval.
- Не пушить и не мержить напрямую в `main`.
- Не ослаблять guardrails вокруг прав на документы, beta allowlist, cost caps, kill switch, secret redaction и raw document text redaction.
- Не показывать payment UI и не запускать paid jobs до Gate C.
- Не расширять beta formats за пределы TXT/DOCX/EPUB без отдельного решения владельца.
- Не реализовывать FB2 из GitHub issue
  [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23) без
  owner approval, Architect review, supported-subset decision, safety plan,
  rights-approved fixtures и отдельной agent-ready implementation issue.
- Не делать большие переписывания без отдельного плана и review.
- Не публиковать admin console в интернет до public-production hardening.
- Не трактовать beta safety accounting как paid ledger.
- Не копировать AGPL code, prompts, file layout, class/function names, tests или implementation details из AGPL-проектов.

## 8. Что считается успехом проекта

Формальные free beta success metrics утверждены владельцем 2026-05-17 в рамках
GitHub issue #71. Метрики разделены на hard launch guardrails и
translation-quality learning metrics.

Hard launch guardrails:

- Gate B complete before free beta.
- Recovery reliability: `0` lost accepted jobs in Gate B
  cancel/resume/bot-restart/worker-restart checks.
- Safety/privacy: `0` known raw document text, prompt, translation or API key
  leaks in logs, admin views, telemetry or artifacts.
- Cost/control: `0` cap or kill-switch breaches.

Translation-quality learning metrics:

- For every completed beta document, collect per-target-language human
  feedback: `usable`, `not usable` or `needs review`, plus short reason tags.
- Existing automated Russian/Ukrainian quality metrics may be used as
  regression diagnostics where reference samples exist.
- Automated Russian/Ukrainian quality scores are not a universal success metric
  for every target language.

## 9. Что не является целью сейчас

- Paid public SaaS или public production launch.
- Paid beta без Telegram Stars/XTR invoice flow, payment ledger, idempotency, refunds, `/paysupport`, reconciliation и support/refund policy.
- Stripe/YooKassa/card flow как immediate Telegram path.
- Subscriptions, referrals, coupons, teams.
- PDF, OCR, MOBI, FB2, batch ZIP или arbitrary file parser.
- FB2 из GitHub issue
  [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23) остается
  deferred idea: owner decision TBD, authorized FB2 fixtures Unknown,
  dependency impact Unknown.
- Public website/customer portal.
- WhatsApp, Discord, public API или другие каналы.
- User-facing provider/model picker.
- Arbitrary custom prompts или full glossary UI.
- Public admin exposure.
- Advanced BI и большие product expansions до стабилизации closed beta.
- Repo-wide ruff cleanup как release blocker.

## 10. Как AI-агенты должны использовать этот файл

- Orchestrator Agent читает этот brief перед разбиением больших целей на маленькие задачи и сверяет их с текущей стадией.
- Architect Agent проверяет, не нарушают ли предложения ограничения, release gates, privacy/security/payment/deployment guardrails.
- Scribe Agent обновляет этот файл, когда меняются стадия проекта, целевые сценарии, ограничения, release gates или подтвержденные факты.
