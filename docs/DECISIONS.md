# Decisions

## Как пользоваться этим документом

Это журнал уже принятых продуктовых, архитектурных, процессных и рискованных решений FolioLoom.
AI-агенты обязаны читать его перед архитектурными, продуктовыми, релизными и рискованными задачами.
Если решение не зафиксировано здесь или в явно указанном активном source of truth, агент не должен считать его принятым.
Новые решения добавляются только после явного approve человека; черновики и планы без approve фиксируются как `Proposed` или `Unknown`.

## Decision status

- Active - действует сейчас.
- Proposed - предложено, но не утверждено.
- Superseded - заменено новым решением.
- Deprecated - больше не используется.
- Unknown - видно из проекта, но неясно, решение ли это.

## Принятые решения

### 2026-05-10 - Product decisions: free closed beta first

Status: Active

Decision:
- FolioLoom сейчас строится как Telegram-first closed-beta foundation.
- Следующий milestone - free closed beta.
- Paid launch и public production не считаются готовыми.

Evidence:
- `README.md`: Current Status, Supported / Not Supported, Beta Safety / Cost Guard.
- `CURRENT_PROJECT_STATE.md`: "Ближайшая цель - free closed beta".
- `docs/restart/folioloom-restart-spec.md`: Restart Decision.
- `docs/restart/release-gates.md`: Gate B, Gate C, Gate D.

Reason:
- Документы явно фиксируют staged rollout: сначала доверенная бесплатная beta, потом paid beta только после payment/readiness gate, затем public production.

Consequences:
- Разработка должна приоритизировать надежность closed beta, а не публичный SaaS.
- AI-агентам нельзя добавлять public production claims, paid launch path или публичную воронку без approve владельца.

Human approval required to change:
- yes; это меняет продуктовую стадию, риски, релизные gate-ы и ожидания пользователей.

### 2026-05-10 - Product decisions: Telegram-first для авторизованных длинных документов

Status: Active

Decision:
- Основной пользовательский канал - Telegram.
- Сервис переводит только документы, на которые у пользователя есть права: книги, главы, рукописи, редакторские материалы, public-domain и rights-holder документы.
- Текущая аудитория - доверенные beta-пользователи из invite-only cohort и owner/admin.

Evidence:
- `README.md`: What FolioLoom Does.
- `docs/PROJECT_BRIEF.md`: разделы 1-3 и 5.
- `docs/restart/folioloom-restart-spec.md`: Product Definition.

Reason:
- Все активные продуктовые документы описывают один и тот же Telegram-first сценарий и rights-confirmation boundary.

Consequences:
- AI-агентам нельзя переориентировать продукт на public website, WhatsApp/Discord/API или "translate any copyrighted book" без отдельного решения.
- Любые изменения upload/translation flow должны сохранять rights confirmation и безопасные сообщения пользователю.

Human approval required to change:
- yes; изменение канала или аудитории меняет продукт и legal/privacy risk.

### 2026-05-10 - Product decisions: MVP scope для beta

Status: Active

Decision:
- MVP для free closed beta ограничен TXT, DOCX и EPUB.
- MVP включает upload, validation, rights confirmation, target language selection, estimate, confirmation, persistent jobs/work units, worker processing, progress/cancel, partial/final result, My Books/history/resume/delete, beta allowlist, cost caps, kill switch, admin visibility и backup/restore workflow.
- Не делаем сейчас: paid public SaaS, public self-serve signup, PDF/OCR/MOBI/FB2/batch ZIP, arbitrary parser, public admin, subscriptions, referrals, coupons, teams, user-facing provider/model picker.
- FB2 support from GitHub issue [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23) is a deferred idea only. It does not change the beta MVP unless the owner approves a scope change and Architect review defines the supported subset, parser/resource safety plan, fixture rights basis, dependency impact and verification plan.

Evidence:
- `README.md`: Supported / Not Supported.
- `docs/PROJECT_BRIEF.md`: Основные сценарии, Что не является целью сейчас.
- `docs/restart/folioloom-restart-spec.md`: Required Closed-Beta Flow, Do Not Build Yet.
- `docs/restart/release-gates.md`: Gate B.

Reason:
- MVP scope повторяется в README, project brief, restart spec и release gates.

Consequences:
- AI-агентам нельзя расширять форматы или строить платежные/публичные функции как часть текущего MVP.
- Gaps из Gate B остаются задачами до free closed beta, но не означают readiness.
- Агенты не должны превращать issue #23 в implementation task без отдельного owner decision, architecture review и agent-ready issue.

Human approval required to change:
- yes; расширение MVP меняет сроки, QA matrix, security и support scope.

### 2026-05-10 - Architecture decisions: backend является source of truth

Status: Active

Decision:
- Backend, persistent jobs/work units и object storage являются durable source of truth.
- Telegram bot state - adapter, а не durable state.
- Progress derives from work units; cancel/resume/restart должны быть safe/idempotent enough for beta.

Evidence:
- `docs/restart/folioloom-restart-spec.md`: Backend Invariants.
- `README.md`: What FolioLoom Does.
- `CURRENT_PROJECT_STATE.md`: Backend, persistence and worker.
- `src/translator_service/worker.py`, `src/translator_service/persistent_jobs.py`, `src/translator_service/postgres_scheduler.py`.

Reason:
- Код и документы показывают persistent job/work-unit architecture вместо in-memory prototype.

Consequences:
- AI-агентам нельзя переносить durable correctness в Telegram bot memory.
- Изменения job/work-unit state machine требуют focused plan, tests и review.

Human approval required to change:
- yes; это базовый архитектурный инвариант и затрагивает надежность данных.

### 2026-05-10 - Architecture decisions: runtime services and deployment shape

Status: Active

Decision:
- Server runtime использует Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- `api` - FastAPI health/admin app; `bot` - aiogram Telegram runtime; `worker` - background translation worker.
- Runtime files монтируются как `./var -> /app/var` и `./var -> /data`.

Evidence:
- `docker-compose.yml`.
- `Dockerfile`.
- `README.md`: Deployment Overview.
- `docs/deployment/admin-vps-runbook.md`.
- `docs/deployment/restore-runbook.md`.

Reason:
- Compose и runbook-и прямо фиксируют текущую service topology.

Consequences:
- AI-агентам нельзя менять deployment approach, service names, mounts или server scripts без explicit approval.
- Deployment docs и smoke checks должны оставаться согласованы с compose.

Human approval required to change:

### 2026-05-10 - Architecture decisions: database and storage

Status: Active

Decision:
- Server runtime использует `SCHEDULER_BACKEND=postgres` для scheduler/job/work-unit state.
- SQLite остается fallback/runtime store там, где явно настроено.
- Local object storage хранит source, intermediate, partial и final files под runtime roots.
- PostgreSQL data lives in Docker volume `postgres-data`.

Evidence:
- `.env.server.example`.
- `docker-compose.yml`.
- `README.md`: Deployment Overview.
- `CURRENT_PROJECT_STATE.md`: Текущий стек.
- `docs/restart/folioloom-restart-spec.md`: Worker, scheduler and object storage rules.

Reason:
- Env contract, compose и docs совпадают: Postgres - server scheduler backend, local object storage - текущая storage модель.

Consequences:
- AI-агентам нельзя создавать migrations, менять state layer, retention или runtime data paths без approve.
- Production correctness не должна зависеть от SQLite-only assumptions.

Human approval required to change:
- yes; это database/user-data/deployment зона.

### 2026-05-10 - Architecture decisions: external APIs are internal provider layer

Status: Active

Decision:
- Telegram Bot API - пользовательский канал.
- DeepSeek-compatible chat completion providers - внутренний provider layer.
- Provider/model picker не является user-facing feature.
- Admin/env DeepSeek keys are additive; real keys and raw document text must not be exposed.

Evidence:
- `README.md`: Product intro, Deployment Overview.
- `.env.server.example`.
- `CURRENT_PROJECT_STATE.md`: Provider layer.
- `docs/restart/folioloom-restart-spec.md`: Admin rules, Payment boundaries.
- `src/translator_service/deepseek_client.py`, `src/translator_service/ai_provider_runtime.py`, `src/translator_service/deepseek_key_pool.py`.

Reason:
- Документы и код показывают provider abstraction, key pool и admin visibility без пользовательского выбора модели.

Consequences:
- AI-агентам нельзя выводить provider details в user UX или раскрывать ключи.
- Provider failures должны давать diagnosable metadata без raw text leakage.

Human approval required to change:
- yes; external API, secrets и user-facing UX являются high-risk зонами.

### 2026-05-10 - Architecture decisions: admin remains SSH-tunnel-only

Status: Active

Decision:
- Closed-beta admin console доступна только через SSH tunnel.
- `/admin` не должен публиковаться в интернет до public-production hardening.

Evidence:
- `README.md`: Current Status, Deployment Overview.
- `docs/deployment/admin-vps-runbook.md`: Network Model.
- `docs/restart/folioloom-restart-spec.md`: Admin rules.
- `docker-compose.yml`: `127.0.0.1:62062:8000`.

Reason:
- README, compose и VPS runbook показывают loopback-bound admin через tunnel.

Consequences:
- AI-агентам нельзя менять bind address, public routing, access model или admin hardening assumptions без approval.
- Любая admin exposure задача должна идти через security/release gate.

Human approval required to change:
- yes; это security/deployment decision.

### 2026-05-10 - Architecture decisions: background jobs and scheduler capacity

Status: Active

Decision:
- Work выполняется через background worker loop и scheduler/work units.
- Worker-side concurrency задается `TRANSLATION_MAX_PARALLEL_UNITS`, provider calls дополнительно ограничены key/channel capacity.
- Scheduler fairness caps не дают одному user/job/document монополизировать capacity.

Evidence:
- `README.md`: Deployment Overview.
- `.env.server.example`.
- `CURRENT_PROJECT_STATE.md`: Backend, persistence and worker.
- `src/translator_service/worker.py`, `src/translator_service/scheduler_runner.py`, `src/translator_service/scheduler.py`.

Reason:
- Текущий runtime и env contract явно разделяют worker capacity, provider capacity и scheduler fairness.

Consequences:
- AI-агентам нельзя увеличивать concurrency как быстрый фикс без проверки provider health, cost caps и scheduler correctness.
- Scheduler/runtime changes требуют targeted tests.

Human approval required to change:
- yes; affects cost, provider reliability and durable job processing.

### 2026-05-14 - Reliability decisions: issue #30 cancel/provider safeguards

Status: Active

Decision:
- Automatic Telegram result delivery from cancel/finalization paths is
  idempotent per job/result within a running bot process. Manual My
  Books/history downloads remain allowed after automatic delivery.
- Admin bulk provider key testing must pause while admin metadata reports active
  translations or active provider requests, before reading provider key secrets
  or starting external `/models` probes.
- Worker/scheduler provider-failure retry metadata must stay safe and generic;
  raw provider/source/key/traceback details must not leak into retry metadata,
  scheduler events or logs.

Evidence:
- GitHub issue [#30](https://github.com/ogirkoviylord/folioloom_main/issues/30)
  was split into issues #32-#35 and closed after the child work completed.
- PR #36 documented the root-cause discovery.
- PR #37 implemented in-process automatic result delivery idempotency.
- PR #38 guarded Admin -> AI Providers -> Test all active keys during active
  translations/provider requests and updated operator docs.
- PR #39 added worker/scheduler provider-failure regression coverage and safe
  retry metadata checks.

Reason:
- The owner-reported incident combined admin bulk key tests during active
  translation, a stalled/cancelled job, and duplicate Telegram result delivery.
  The fix keeps each risky boundary small: bot automatic delivery idempotency,
  admin probe guarding, and safe provider-failure metadata.

Consequences:
- Durable cross-restart automatic delivery tracking remains out of scope and
  must not be claimed as implemented.
- Admin bulk key testing can be unavailable during active translations or when
  active-translation metadata is unavailable; this is intentional fail-closed
  behavior.
- Provider reliability follow-up issue #31 remains separate from issue #30.

Human approval required to change:
- yes; changes affect user-facing bot delivery, admin provider controls,
  external provider behavior and scheduler/job reliability boundaries.

### 2026-05-10 - Testing approach: local gates first, minimal CI workflow present

Status: Active

Decision:
- Основные verification commands: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall src`, `scripts/predeploy_check.sh`.
- `scripts/predeploy_check.sh` является текущим predeploy gate.
- Repo-wide ruff cleanup не является free closed-beta release blocker.
- `.github/workflows/checks.yml` exists as a minimal GitHub Actions workflow for compile and unit tests on PRs and pushes to `main`; current run/pass status remains Unknown unless checked on a PR/checks page.

Evidence:
- `README.md`: Verification Commands.
- `docs/restart/release-gates.md`: Common Verification Commands.
- `CURRENT_PROJECT_STATE.md`: Последняя зафиксированная проверка.
- `pyproject.toml`: dev dependencies and ruff config.
- `.github/workflows/checks.yml`: Python 3.13 compile and unit test workflow.

Reason:
- Репозиторий фиксирует local verification gates and now contains a minimal
  GitHub Actions workflow, but active release/readiness docs still require
  explicit evidence before claiming tests or CI passed.

Consequences:
- AI-агентам нельзя утверждать, что CI passed, без видимого PR/check evidence.
- Для code changes нужно запускать focused tests и релевантные local gates; для docs-only changes можно не запускать test suite, если это явно указано в отчете.

Human approval required to change:
- no for adding evidence to this decision; yes for changing release gates or CI policy.

### 2026-05-13 - Process decisions: repository guardrails

Status: Active

Decision:
- Работать small focused diffs.
- Не менять код без явной задачи.
- Не пушить напрямую в `main`.
- Не добавлять production dependencies без explicit human approval.
- Не делать production deployment без explicit human approval.

Evidence:

Reason:
- Это прямые repository rules.

Consequences:
- AI-агентам нельзя расширять scope задачи или выполнять git/deploy/dependency actions без нужного approval.
- Документация должна отделять confirmed facts от assumptions.

Human approval required to change:
- yes; это правила владельца репозитория.

### 2026-05-13 - Process decisions: documentation update rules

Status: Active

Decision:
- При создании/обновлении документации нужно читать README, docs и relevant project files.
- Нельзя выдумывать features, architecture, tests, CI, deployment steps или production readiness.
- Использовать `TBD` для human decisions и `Unknown` там, где evidence недостаточно.
- Не ослаблять safety, legal, privacy, security, payment или deployment guardrails.

Evidence:

Reason:
- Эти правила прямо заданы для документации и AI-agent handoff.

Consequences:
- AI-агентам нельзя превращать specs/plans в факты без сверки с active source of truth.
- Старые plans/specs не являются roadmap без подтверждения.

Human approval required to change:
- yes; это процессный guardrail.

### 2026-05-10 - Risk / safety decisions: beta safety is not billing

Status: Active

Decision:
- Cost-aware beta safety layer ограничивает throughput через reservation-at-enqueue, global/user caps, usage accounting и kill switch.
- Это operational beta guard, а не paid beta billing ledger.
- Telegram Stars/XTR и payment ledger остаются отдельным release gate.

Evidence:
- `README.md`: Beta Safety / Cost Guard.
- `CURRENT_PROJECT_STATE.md`: Backend, persistence and worker.
- `docs/deployment/admin-vps-runbook.md`: Beta Safety / Cost Guard.
- `docs/restart/release-gates.md`: Gate C.

Reason:
- Документы прямо отделяют beta safety accounting от paid billing.

Consequences:
- AI-агентам нельзя трактовать budget telemetry как платежный ledger.
- Нельзя запускать paid jobs или payment UI до Gate C.

Human approval required to change:
- yes; payment/pricing/revenue handling requires owner approval.

### 2026-05-10 - Risk / safety decisions: raw text and secrets redaction

Status: Active

Decision:
- Logs/admin/safety telemetry must not expose raw document text, prompts, translations or API keys.
- Admin may show metadata, provider health, costs and safe diagnostics.
- Secrets must be masked; admin-managed DeepSeek keys are encrypted when `ADMIN_SECRET_MASTER_KEY` is configured.

Evidence:
- `README.md`: Beta Safety / Cost Guard, Deployment Overview.
- `.env.server.example`.
- `docs/restart/upload-safety-and-retention.md`: Logs And Admin Safety.
- `docs/restart/folioloom-restart-spec.md`: Backend Invariants, Admin rules.
- `src/translator_service/admin/secrets.py`, `src/translator_service/security_telemetry.py`.

Reason:
- Safety and admin docs repeatedly define redaction and metadata-only visibility.

Consequences:
- AI-агентам нельзя добавлять logging/admin views with raw document text or real secrets.
- Debug artifacts and downloadable run archives must be checked for leakage before beta.

Human approval required to change:
- yes; это privacy/security/user-data boundary.

### 2026-05-10 - Risk / safety decisions: upload safety and retention baseline

Status: Proposed

Decision:
- Closed beta should accept only `.txt`, `.docx` and `.epub`.
- Service should not trust filename or content-type alone.
- Default retention proposal: source 7 days, final 30 days, partial 14 days, quarantine 7 days, logs metadata only.

Evidence:
- `docs/restart/upload-safety-and-retention.md`.
- `docs/restart/release-gates.md`: upload hardening and TTL cleanup are unchecked Gate B items.

Reason:
- Правила описаны как baseline, но release gates показывают, что upload hardening/quarantine and TTL cleanup еще не complete.

Consequences:
- AI-агентам нельзя считать upload hardening или TTL cleanup fully implemented без additional evidence.
- Реализация retention/delete behavior требует care around user data and backups.

Human approval required to change:
- yes; user data retention and parser safety require owner approval.

### 2026-05-10 - Risk / safety decisions: payments and pricing are gated

Status: Active

Decision:
- No payment UI is exposed in free closed beta.
- No paid job can start before payment/credit capture in paid beta.
- Telegram Stars/XTR is the first paid-beta path.
- Stripe/YooKassa/card flow is not the immediate Telegram path.
- Pricing docs are draft only until Gate C.

Evidence:
- `docs/restart/folioloom-restart-spec.md`: Payment boundaries.
- `docs/restart/release-gates.md`: Gate B and Gate C.
- `DOCUMENT_INDEX.md`: Paid-Beta Draft Docs.
- `docs/superpowers/specs/2026-05-09-folioloom-pricing-v0.md` exists as draft.

Reason:
- Active docs explicitly block paid beta until payment flow, ledger, idempotency, refunds, support and reconciliation are implemented.

Consequences:
- AI-агентам нельзя добавлять payment UI, paid job path, pricing changes or payment-provider integration without approve.
- Draft pricing must not be treated as production pricing.

Human approval required to change:
- yes; payments/pricing require explicit human approval.

### 2026-05-10 - Risk / safety decisions: public production is not ready

Status: Active

Decision:
- Public production is not ready.
- Public admin hardening, legal/privacy/AUP/refund docs, support workflow, incident runbooks, stronger parser/AV, offsite backups and monitoring remain future gates.

Evidence:
- `README.md`: Current Status.
- `docs/restart/release-gates.md`: Gate D.
- `docs/PROJECT_BRIEF.md`: Что не является целью сейчас.

Reason:
- Gate D contains unchecked public-production requirements.

Consequences:
- AI-агентам нельзя маркировать проект production-ready.
- Нельзя делать public exposure, legal/privacy changes, support promises or production deployment без explicit approval.

Human approval required to change:
- yes; release readiness requires owner go/no-go.

### 2026-05-10 - Process decisions: AI orchestration roles

Status: Active

Decision:
- Future AI workflow assumes Orchestrator, Architect, Implementer, Reviewer and Scribe Agent roles.

Evidence:
- `docs/PROJECT_BRIEF.md`: AI-agent usage.

Reason:
- Repository rules and project brief both name role expectations.

Consequences:
- Large tasks should be split, risk-reviewed, implemented in small diffs, reviewed, and documented.
- AI-агентам нельзя skip review/scribe expectations for broad or risky work.

Human approval required to change:
- no for clarifying role usage; yes for changing repository workflow.

## Decisions that still need human approval

- Decision needed: формальный go/no-go для free closed beta.
  Why it matters: Gate B still has unchecked release blockers.
  Suggested options: hold; limited trusted beta with signed deferrals; complete all Gate B items first.
  Recommended default: complete/record Gate B evidence before opening beta.
  Risk if left undecided: agents may confuse foundation readiness with beta approval.

- Decision needed: support/refund/reconciliation policy for paid beta.
  Why it matters: paid launch is blocked until Gate C.
  Suggested options: Telegram Stars/XTR only; postpone paid beta; define refund/support manual process first.
  Recommended default: postpone paid beta until ledger, support and reconciliation are implemented and tested.
  Risk if left undecided: payment work may start without operational/legal guardrails.

- Decision needed: legal/privacy/AUP documents for public production.
  Why it matters: users upload long documents and rights-sensitive content.
  Suggested options: owner-authored policy; counsel-reviewed policy; keep public production blocked.
  Recommended default: keep public production blocked until policies are approved.
  Risk if left undecided: privacy/legal claims may be invented by agents.

- Decision needed: public admin hardening approach.
  Why it matters: current admin is SSH-tunnel-only.
  Suggested options: keep tunnel-only; add HTTPS plus stronger access layer; add named admins/MFA or equivalent.
  Recommended default: keep tunnel-only for closed beta.
  Risk if left undecided: accidental public admin exposure.

- Decision needed: offsite backup and scheduled restore rehearsal policy.
  Why it matters: current docs define restore rehearsal, but public-production offsite backup is still a gate.
  Suggested options: manual owner runbook; scheduled offsite backups; managed backup service.
  Recommended default: require restore rehearsal evidence before beta and offsite backups before public production.
  Risk if left undecided: backup existence may be mistaken for recoverability.

- Decision needed: exact success metrics for beta.
  Why it matters: `docs/PROJECT_BRIEF.md` marks formal success metrics as `TBD`.
  Suggested options: quality threshold; completion/cancel/restart reliability; cost cap adherence; user feedback target.
  Recommended default: define a small metrics set before beta go/no-go.
  Risk if left undecided: agents optimize for implementation volume instead of beta learning.

- Decision needed: CI policy.
  Why it matters: `.github/workflows/checks.yml` exists, but required-vs-advisory PR policy and expansion scope are not recorded.
  Suggested options: keep current workflow advisory; require the existing checks for PRs; expand GitHub Actions only after owner-approved scope.
  Recommended default: keep local gates as required and treat CI status as Unknown unless visible PR/check evidence is inspected.
  Risk if left undecided: agents may overstate CI coverage or merge expectations.


- Не менять production deployment без явного человека.
- Не менять payment/pricing без явного человека.
- Не менять legal/privacy/security/auth без явного человека.
- Не менять user data handling, retention, backup/restore или database migrations без явного человека.
- Не добавлять новые production dependencies без явного человека.
- Не пушить напрямую в `main`.
- Не публиковать admin console в интернет без approved hardening plan.
- Не считать beta safety accounting платежным ledger.
- Не считать проект production-ready.
- Не расширять beta formats за пределы TXT/DOCX/EPUB без отдельного решения.
- Не реализовывать FB2 из GitHub issue #23 без owner approval, Architect review и отдельного agent-ready implementation issue.
- Не переписывать архитектуру без отдельного approved plan.
- Не трактовать historical plans/specs as current roadmap без сверки с active source of truth.
- Не хранить и не показывать raw document text, prompts, translations или API keys в logs/admin/safety telemetry.
