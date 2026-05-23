# Handoff

Last updated: 2026-05-23

## 1. Текущее состояние проекта

FolioLoom сейчас описан как Telegram-first сервис перевода авторизованных
длинных документов. Текущий подтвержденный формат продукта: доверенный
beta-пользователь загружает TXT/DOCX/EPUB в Telegram, подтверждает права,
выбирает translation mode и target language, получает free preview, явно
нажимает Continue перед полным переводом, получает
progress/cancel/status/history flow и финальный или частичный результат через
backend-first workflow.

Стадия: active development / working closed-beta foundation. Репозиторий прямо
говорит, что это уже не in-memory prototype: есть persistent jobs/work units,
object storage, worker loop, admin console, Docker Compose deployment,
backup/restore workflow и широкий unittest suite. Следующий milestone -
free closed beta.

Что уже работает по документации и коду: Telegram bot runtime, FastAPI
health/admin app, persistent job/work-unit foundation, worker/scheduler,
TXT/DOCX/EPUB adapters, DeepSeek-compatible provider layer, admin visibility,
beta allowlist, rights confirmation, beta cost/cap guard, Docker Compose stack
и backup/restore scripts.

Issue #30 reliability update on 2026-05-14: GitHub issues
[#32](https://github.com/ogirkoviylord/folioloom_main/issues/32)-[#35](https://github.com/ogirkoviylord/folioloom_main/issues/35)
are closed and PRs #36-#39 are merged. The work documented the root cause,
made automatic cancel/partial result delivery idempotent within a running bot
process, paused admin bulk key tests during active translations/provider
requests, and added scheduler/worker provider-failure regression coverage with
safe retry metadata. This does not make cancel/resume/restart Gate B fully
complete and does not prove durable cross-restart automatic delivery tracking.

Что пока нестабильно или не закрыто для beta:
upload hardening/quarantine baseline, local malware/AV scanning gate,
TTL cleanup/delete verification, real-file
TXT/DOCX/EPUB release matrix, local/offline EPUBCheck validation, DOCX
openability/visual QA, Alerts MVP, Backups visibility, restore rehearsal artifact,
cancel/resume/restart release evidence и server smoke evidence.

Что неизвестно: `.github/workflows/checks.yml` существует, но current branch
GitHub Actions run/pass status Unknown until a PR check exists; public
production readiness не подтверждена.

Owner decisions recorded during issue #71:

- 2026-05-16: free closed beta waits for complete Gate B evidence; no implicit
  Gate B deferrals are approved.
- 2026-05-17: free beta success metrics split hard launch guardrails from
  translation-quality learning metrics. Hard guardrails are Gate B complete,
  `0` lost accepted jobs, `0` known raw text/prompt/translation/API key leaks
  and `0` cap or kill-switch breaches. Translation quality is collected as
  per-target-language human feedback; existing Russian/Ukrainian automated
  scores remain regression diagnostics, not universal launch metrics.
- 2026-05-17: Gate B real-file corpus may use public-domain or clearly
  permissive-licensed documents from free libraries and other internet sources
  when the manifest records source/license URL and rights basis. "Free to read
  online" alone is not sufficient. Synthetic fixtures may live in repo; raw real
  source documents and translated outputs stay out of git by default.
- 2026-05-17: retention/delete verification may run on synthetic test data by
  default and on an owner-approved disposable beta/runtime copy only. Agents
  must not run TTL cleanup/delete checks on live beta/server data.
- 2026-05-17: Gate B backup/restore evidence may be collected only in
  owner-approved disposable local compose, disposable VPS/test server,
  disposable beta-runtime copy or explicitly approved beta environment. Running
  backup/restore checks on live beta/server data requires exact-run owner
  approval. Release artifacts must be metadata-only.
- 2026-05-17: GitHub Actions Python checks are advisory for now. Local gates
  remain required for PR-ready work, and agents must report CI status as
  `Unknown` unless visible PR/check evidence was inspected.
- 2026-05-17: Gate B DOCX visual QA uses local LibreOffice Writer. A DOCX
  fixture passes only if it opens without repair/recovery prompt and has no
  blocker visual issues; pixel-perfect source parity is not required.
- 2026-05-17: Gate B Alerts/Backups visibility should be collected as a
  metadata-only owner runbook/report for free beta. New admin UI for these
  signals is deferred to a later follow-up so the admin console does not need a
  broad redesign for each bot feature.
- 2026-05-17: Gate B EPUB validation uses local/offline EPUBCheck as the
  required validation tool. Online EPUB validators are not approved. EPUBCheck
  is a release verification tool, not a production dependency; errors block
  fixtures and warnings are recorded/triaged.

## 2. Текущий фокус

Текущий рабочий фокус по репозиторию: prepare free closed beta by stabilizing
core flow, release gates, operational visibility and documentation.

Подтвержденные подпункты фокуса:

- закрыть Gate B blockers для free closed beta;
- улучшить upload safety, TTL/delete verification и real-file QA;
- добавить local malware/AV scanning gate как часть upload safety; owner
  accepted this direction on 2026-05-22, but implementation evidence is still
  Unknown;
- подтвердить scheduler/runtime consistency, restart/cancel/resume behavior и
  backup/restore readiness;
- держать payments, public production, public admin и новые форматы вне
  текущего scope.
- GitHub issue [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23)
  about FB2 is a deferred idea only; owner decision TBD, authorized fixtures
  Unknown and dependency impact Unknown.

## 3. Что уже работает

- Feature / component: Telegram-first upload/translation flow.
- Evidence: `README.md`, `CURRENT_PROJECT_STATE.md`,
  `src/translator_service/bot/runtime.py`,
  `src/translator_service/bot_translation_service.py`,
  `tests/test_bot_runtime.py`, `tests/test_bot_translation_service.py`.
- Confidence: high.

- Feature / component: Rights confirmation before full processing.
- Evidence: `CURRENT_PROJECT_STATE.md`, `docs/restart/folioloom-restart-spec.md`,
  bot message/runtime modules and related bot tests.
- Confidence: high.

- Feature / component: Free preview before full translation.
- Evidence: PRs #57, #58, #59, #61 and #67 are merged. Local issue #56
  verification on 2026-05-16: focused preview/bot/service suite
  `Ran 237 tests`, `OK`; full unittest suite `Ran 1046 tests`, `OK`,
  `skipped=13`; `PYTHONPATH=src python3 -m compileall src` passed;
  `scripts/predeploy_check.sh` passed. Visible GitHub `Python checks` for PRs
  #57/#58/#59/#61/#67 were successful. This checks the preview slice only and
  does not complete Gate B.
- Confidence: high.

- Feature / component: Invite-only beta allowlist with admin toggle.
- Evidence: `README.md`, `CURRENT_PROJECT_STATE.md`,
  `docs/restart/release-gates.md`, `src/translator_service/beta_access.py`,
  admin settings modules and `tests/test_beta_access.py`.
- Confidence: high.

- Feature / component: Persistent jobs/work units and worker loop.
- Evidence: `CURRENT_PROJECT_STATE.md`, `src/translator_service/persistent_jobs.py`,
  `src/translator_service/persistent_job_store.py`,
  `src/translator_service/worker.py`, `src/translator_service/scheduler_runner.py`,
  scheduler and worker tests.
- Confidence: high.

- Feature / component: PostgreSQL scheduler backend for server runtime.
- Evidence: `README.md`, `docker-compose.yml`,
  `src/translator_service/postgres_scheduler.py`,
  `tests/test_postgres_scheduler.py`.
- Confidence: high.

- Feature / component: TXT/DOCX/EPUB translation foundations.
- Evidence: `CURRENT_PROJECT_STATE.md`,
  `src/translator_service/format_adapters/`, `persistent_planner.py`,
  `persistent_assembly.py`, `translation_runner.py`, format adapter and
  translation tests.
- Confidence: high.

- Feature / component: DeepSeek-compatible provider layer with key pool,
  telemetry and adaptive throttling.
- Evidence: `README.md`, `CURRENT_PROJECT_STATE.md`,
  `src/translator_service/deepseek_client.py`,
  `src/translator_service/deepseek_key_pool.py`,
  `src/translator_service/ai_provider_runtime.py`,
  `src/translator_service/provider_throttle.py`, related provider tests;
  PR #39 added worker/scheduler provider-failure regression coverage and safe
  retry metadata checks; issue #31 implementation classifies unsafe
  model-output failures as `unsafe_model_output` without degrading provider
  channels or reducing adaptive capacity.
- Confidence: high.

- Feature / component: SSH-tunneled FastAPI admin console.
- Evidence: `README.md`, `docs/deployment/admin-vps-runbook.md`,
  `src/translator_service/api.py`, `src/translator_service/admin/`,
  `tests/test_admin_*.py`; PR #38 added a guard so Admin -> AI Providers ->
  Test all active keys pauses during active translations or active provider
  requests.
- Confidence: high.

- Feature / component: Automatic result delivery idempotency.
- Evidence: PR #37 updated `src/translator_service/bot/runtime.py` and
  `src/translator_service/bot_translation_service.py` so automatic
  cancel/finalization result delivery is idempotent per job/result in a running
  bot process while manual My Books/history downloads remain available.
- Confidence: medium.

- Feature / component: Operational beta safety guard.
- Evidence: `README.md`, `CURRENT_PROJECT_STATE.md`,
  `docs/restart/release-gates.md`, `src/translator_service/beta_safety.py`,
  `src/translator_service/beta_safety_store.py`, `tests/test_beta_safety.py`,
  `tests/test_beta_safety_store.py`.
- Confidence: high.

- Feature / component: Local verification gates.
- Evidence: `README.md` lists `PYTHONPATH=src python3 -m unittest discover -s tests`,
  `PYTHONPATH=src python3 -m compileall src` and `scripts/predeploy_check.sh`;
  `tests/` contains 93 `test_*.py` files.
- Confidence: medium.

- Feature / component: Deferred worker failure run-log finalization.
- Evidence: PR #21 / commit `a28f1b4` updates `scheduler_runner.py` and
  `worker.py` so scheduled worker failures finish matching running translation
  run logs as `failed` with a generic safe error message. Local verification
  reported on 2026-05-13: focused scheduler/worker tests, worker/scheduler
  suites, `PYTHONPATH=src python3 -m compileall src`,
  `PYTHONPATH=src python3 -m unittest discover -s tests` with 984 tests OK and
  13 skipped, and `git diff --check`. GitHub Actions status is Unknown until
  PR checks are inspected.
- Confidence: medium.

## 4. Что работает частично или нестабильно

- Area: Translation modes.
- Current behavior: Issues #44, #45, #46 and #55 are merged: after upload
  validation and rights confirmation, the bot requires a mode choice before
  target language selection; created persistent jobs retain selected mode in
  safe translation-policy metadata; DOCX full-translation planning routes
  `document_form` and `book_manuscript` differently; preview generation consumes
  selected mode metadata when available and keeps safe default behavior when it
  is absent.
- Evidence: `src/translator_service/bot/runtime.py`,
  `src/translator_service/bot/messages.py`,
  `src/translator_service/bot_translation_service.py`,
  `src/translator_service/format_adapters/docx.py`,
  `src/translator_service/persistent_planner.py`,
  `tests/test_bot_runtime.py`, `tests/test_bot_translation_service.py`,
  `tests/test_translation_jobs.py`, `tests/test_format_adapters.py`,
  `tests/test_persistent_planner.py`, PR #67.
- Risk: translation mode behavior still needs real-file release validation before
  beta readiness claims.
- Suggested next task: include mode-specific preview/full-translation scenarios
  in the real-file matrix or Gate B evidence report where relevant.

- Area: Upload hardening/quarantine.
- Current behavior: Policy exists; release gate remains unchecked. Code has
  upload validation and document sandbox modules, but release docs do not claim
  complete quarantine baseline. Owner accepted adding a local malware/AV
  scanning gate on 2026-05-22; implementation is not yet confirmed.
- Evidence: `docs/restart/upload-safety-and-retention.md`,
  `docs/restart/release-gates.md`, `src/translator_service/documents.py`,
  `src/translator_service/document_sandbox.py`.
- Risk: unsafe ZIP/container or malware-like inputs could reach parser/worker
  paths if hardening/scanning is incomplete; public external scanning could leak
  rights-sensitive documents if used as the default.
- Suggested next task: Architect defines exact safe baseline from the policy,
  including scanner contract, verdict taxonomy and fail-closed beta behavior;
  Implementer adds missing negative/AV fixtures; Reviewer checks no raw text
  leaks.

- Area: TTL cleanup and delete verification.
- Current behavior: Retention policy is documented, but Gate B marks cleanup
  unchecked.
- Evidence: `docs/restart/upload-safety-and-retention.md`,
  `docs/restart/release-gates.md`.
- Risk: source/final/partial/quarantine objects may be retained longer than
  intended or delete behavior may be unproven.
- Suggested next task: Implementer adds idempotent cleanup/delete verification
  on synthetic test data by default; a second pass may use only an
  owner-approved disposable beta/runtime copy, never live beta/server data.

- Area: Real-file release validation.
- Current behavior: Matrix document exists, but execution/report artifact is
  still unchecked.
- Evidence: `docs/restart/real-file-test-matrix.md`,
  `docs/restart/release-gates.md`, `test_samples/`.
- Risk: unit tests may pass while real DOCX/EPUB/TXT documents fail to open,
  preserve structure or survive restart/cancel scenarios.
- Suggested next task: Scribe/Reviewer create a release report template and run
  authorized public-domain/permissive-license fixtures with recorded source and
  rights basis.

- Area: Admin operational visibility.
- Current behavior: Admin has many surfaces, but Alerts MVP and Backups
  visibility remain active gaps.
- Evidence: `CURRENT_PROJECT_STATE.md`, `DOCUMENT_INDEX.md`,
  `docs/superpowers/specs/2026-05-08-folioloom-admin-console-design.md`.
- Risk: owner may need to inspect logs manually to notice provider, queue,
  worker, disk or backup failures.
- Suggested next task: Implementer adds minimal alerts/backups visibility with
  safe metadata only; Reviewer verifies no secrets/raw text exposure.

- Area: CI.
- Current behavior: Local verification gates are documented and a minimal
  GitHub Actions workflow exists for PRs and pushes to `main`.
- Evidence: `.github/workflows/checks.yml`, `docs/CONTEXT_MAP.md`,
  `docs/PROJECT_BRIEF.md`, local filesystem check.
- Owner decision: GitHub Actions Python checks are advisory for now; local gates
  remain required for PR-ready work.
- Risk: current run/pass status remains Unknown unless a PR/checks page is
  inspected; passing CI does not prove release readiness because
  deploy/server-smoke/real-file/backup-restore evidence still depends on local
  or approved-environment checks.

## 5. Известные проблемы

No explicit known issues found in repository.

Potential issues to verify:

- Problem: Gate B remains incomplete for free closed beta.
- Evidence: unchecked items in `docs/restart/release-gates.md`.
- Impact: foundation readiness could be mistaken for beta approval.
- Suggested fix task: Reviewer produces Gate B evidence report with pass/fail,
  deferrals and owner go/no-go.

- Problem: Provider safety-triggering output could leave provider channels
  degraded.
- Evidence: GitHub issue
  [#31](https://github.com/ogirkoviylord/folioloom_main/issues/31); owner
  approved `unsafe_model_output` semantics on 2026-05-14.
- Impact: issue #31 separates unsafe model-output failures from key/provider
  infrastructure failures, but repeated safety failure retry strategy remains
  TBD.
- Suggested fix task: Reviewer verifies issue #31 diff, focused tests, redaction
  behavior and no worker/scheduler retry change.

- Problem: Full release status is not proven by preview verification alone.
- Evidence: issue #56 local verification ran the focused preview suite, full
  unittest suite, compileall and predeploy check for the preview evidence slice,
  but did not run server smoke, real-file matrix, restore rehearsal or every
  Gate B release check.
- Impact: preview behavior can be evidenced while broader free closed beta
  readiness remains incomplete.
- Suggested fix task: run the remaining Gate B checks before any release
  go/no-go.

- Problem: Upload safety and TTL policies are documented but not fully gate-checked.
- Evidence: `docs/restart/upload-safety-and-retention.md` and unchecked Gate B
  items.
- Impact: parser safety, retention and delete expectations may be unproven.
- Suggested fix task: implement and test negative fixtures, quarantine behavior
  and cleanup/delete verification with human approval.

- Problem: Paid beta is blocked.
- Evidence: `CURRENT_PROJECT_STATE.md`, `docs/restart/release-gates.md`,
  `docs/DECISIONS.md`.
- Impact: no payment UI or paid jobs should be exposed.
- Suggested fix task: keep payment work behind Gate C and owner approval.

- Problem: Public production is not ready.
- Evidence: `README.md`, `docs/restart/release-gates.md`,
  `docs/DECISIONS.md`.
- Impact: admin must stay SSH-tunnel-only; no public launch claims.
- Suggested fix task: defer public production work until Gate D planning and
  human approval.

## 6. Текущие приоритеты

### Immediate

- Задача: produce Gate B evidence report.
  Почему важно: free closed beta depends on checked or explicitly deferred
  blockers.
  Риск: запуск beta без evidence.
  Кто должен делать: Reviewer.
  Можно ли отдавать агенту: yes.

- Задача: verify upload hardening/quarantine baseline.
  Почему важно: unsafe files must not reach workers.
  Риск: parser, storage and raw-text leakage risk.
  Кто должен делать: Architect / Implementer / Reviewer.
  Можно ли отдавать агенту: needs approval if behavior changes user data
  handling or quarantine retention.

- Задача: design and implement local malware/AV scanning gate in split issues.
  Почему важно: untrusted uploads must be scanned before parsing without sending
  private books/manuscripts to public scanning services by default.
  Риск: security, privacy, deployment, dependency and runtime user-data risk.
  Кто должен делать: Architect / Implementer / Reviewer.
  Можно ли отдавать агенту: yes only as split issues; deployment/new dependency,
  external scanning, retention or runtime-data behavior needs explicit owner
  approval.
  Issues: [#91](https://github.com/ogirkoviylord/folioloom_main/issues/91)
  design, [#92](https://github.com/ogirkoviylord/folioloom_main/issues/92)
  scanner contract, [#93](https://github.com/ogirkoviylord/folioloom_main/issues/93)
  ClamAV adapter, [#94](https://github.com/ogirkoviylord/folioloom_main/issues/94)
  upload-flow wiring, [#95](https://github.com/ogirkoviylord/folioloom_main/issues/95)
  Gate B evidence.

- Задача: run release-scoped verification before any go/no-go.
  Почему важно: issue #56 recorded current preview-slice tests, but Gate B still
  needs release evidence for server smoke, real files, restore/backups and
  restart scenarios.
  Риск: preview evidence could be mistaken for full beta readiness.
  Кто должен делать: Reviewer.
  Можно ли отдавать агенту: yes.

### Next

- Задача: execute real-file TXT/DOCX/EPUB matrix and create release report.
  Почему важно: unit tests do not replace real-file openability and structure QA.
  Риск: outputs fail in real readers.
  Кто должен делать: Reviewer / Scribe.
  Можно ли отдавать агенту: yes, with public-domain/permissive-license fixtures
  and recorded rights basis only.

- Задача: validate cancel/resume/restart and scheduler/runtime consistency.
  Почему важно: backend is source of truth and beta users need recoverability.
  Риск: accepted jobs disappear or duplicate work claims happen.
  Кто должен делать: Reviewer / Implementer.
  Можно ли отдавать агенту: yes.

- Задача: add metadata-only owner runbook/report for Alerts MVP and Backups
  visibility.
  Почему важно: owner needs operational visibility without manual log reading.
  Риск: missed provider/queue/backup failures.
  Кто должен делать: Implementer / Reviewer.
  Можно ли отдавать агенту: yes, but backup/user-data surfaces may need approval.
  Notes: issue #71 approved owner report first and admin UI later; keep
  metadata-only with no raw docs/prompts/translations/API keys, stack traces,
  backup archives or restored files.

- Задача: verify backup export and restore rehearsal.
  Почему важно: backup existence is not the same as recoverability.
  Риск: beta data cannot be restored.
  Кто должен делать: Reviewer / Architect.
  Можно ли отдавать агенту: yes in owner-approved disposable/local/test/copy
  environments; live beta/server data requires exact-run owner approval.

### Later

- Задача: paid beta planning.
  Почему важно: Gate C is blocked by payment ledger, Stars/XTR, refunds and
  support/reconciliation.
  Риск: payment/legal/support exposure.
  Кто должен делать: Architect / Orchestrator.
  Можно ли отдавать агенту: needs approval.

## 7. Safe tasks for AI agents

- Task: Update docs/HANDOFF.md after a completed verified task.
- Why safe: docs-only update when based on confirmed repo evidence.
- Files likely involved: `docs/HANDOFF.md`.
- Acceptance criteria: confirmed facts separated from Unknown/TBD; no production
  readiness claims invented.
- Tests: not required for docs-only; optionally run markdown/text checks if
  available.
- Risk: stale or overconfident documentation.

- Task: Create a Gate B evidence checklist from existing docs.
- Why safe: reads active docs and summarizes unchecked items.
- Files likely involved: `docs/HANDOFF.md` or a new docs-only report if owner
  requests it.
- Acceptance criteria: every Gate B item has evidence, Unknown, or owner-deferred
  status.
- Tests: not required for docs-only.
- Risk: must not mark unchecked work as complete without evidence.

- Task: Map tests to one module before a focused fix.
- Why safe: read-only investigation.
- Files likely involved: target module and matching `tests/test_*.py`.
- Acceptance criteria: list exact test files and commands to run.
- Tests: no changes required.
- Risk: incomplete mapping if feature spans bot/backend/admin contracts.

- Task: Add or improve focused tests for non-high-risk code paths.
- Why safe: tests-only changes usually do not change production behavior.
- Files likely involved: relevant `tests/test_*.py`.
- Acceptance criteria: new tests fail against the bug or cover the documented
  behavior; no weakened assertions.
- Tests: targeted test command.
- Risk: avoid touching auth/security/payment/user-data expectations casually.

- Task: Produce a real-file matrix report template.
- Why safe: documentation/template work can prepare QA without changing product
  behavior.
- Files likely involved: docs-only report or `docs/restart/real-file-test-matrix.md`
  only if owner requests updates.
- Acceptance criteria: report captures fixture rights, commands, pass/fail,
  output artifacts and known failures.
- Tests: not required for template; later QA commands required when executing.
- Risk: do not add unauthorized copyrighted files.

- Task: Inspect local verification failure and summarize findings.
- Why safe: read-only or test-only debugging can guide next implementation.
- Files likely involved: terminal output, related modules/tests.
- Acceptance criteria: exact failing command, failure, suspected area and next
  focused task.
- Tests: failing command plus any targeted rerun.
- Risk: do not apply broad fixes without a scoped task.

## 8. Risky tasks requiring human approval

- Deployment: production deploy, server changes, Docker Compose topology,
  bind addresses, SSH tunnel model, `scripts/deploy_server.sh`,
  `scripts/server_*`, `docs/deployment/`.
- Secrets: `.env*`, provider keys, Telegram token, admin secret/session settings,
  `ADMIN_SECRET_MASTER_KEY`, encrypted secret storage behavior.
- Database migrations/state: PostgreSQL scheduler schema, SQLite runtime stores,
  persistent job/work-unit schema, backup/restore state and any new migrations.
- Payments/pricing: `pricing.py`, `billing.py`, `orders.py`,
  `order_estimates.py`, `order_payments.py`, Telegram Stars/XTR, ledger,
  refunds, reconciliation, paid jobs, payment UI and pricing docs.
- Auth/security: admin auth/RBAC/session behavior, security telemetry,
  secret redaction, provider key exposure, prompt/model-output safety.
- Legal/privacy: rights/AUP/privacy/refund/support text, user-data handling,
  retention policy, raw document text handling and log/admin display rules.
- User data: runtime `var/`, object storage, backups, restore, TTL cleanup,
  explicit delete, quarantine inspection and real uploaded documents.
- Destructive operations: deleting runtime data, force-resetting git, removing
  artifacts, cleanup scripts that touch user/server data.
- Public API or channel changes: exposing public admin, public website/customer
  portal, WhatsApp/Discord/API channels, user-facing provider/model picker.
- New dependencies: any new production dependency in `pyproject.toml` or runtime
  image.

## 9. Последние изменения

- Date: 2026-05-13.
- Change: Harden translation QA and live monitoring.
- Evidence: git `HEAD` commit `6989c99` changed admin live monitor,
  `translation_runner.py`, `worker.py`, Russian quality checks and related tests.
- Follow-up: run common verification commands before release claims.

- Date: 2026-05-13.
- Change: Harden provider runtime and translation progress.
- Evidence: git commit `e744a43` changed admin live/provider/log views, bot
  runtime, bot translation service, source-pair profiles, translation runner,
  scheduler runner tests and added `tools/epub_audit.py`.
- Follow-up: verify provider/runtime progress behavior through focused tests and
  real-file release matrix.

- Date: 2026-05-13.
- Change: Working tree contains untracked AI orchestration documentation.
- Evidence: `git status --short` shows untracked `AGENTS.md`,
  `docs/CONTEXT_MAP.md`, `docs/DECISIONS.md`, `docs/HANDOFF.md`,
  `docs/PROJECT_BRIEF.md`, `docs/QUALITY_GATES.md`,
  `docs/RELEASE_CHECKLIST.md`, `docs/RISK_REGISTER.md` and
  `docs/ROADMAP.md`.
- Follow-up: owner/Reviewer should decide whether these docs are intended to be
  staged/committed; do not overwrite them casually.

## 10. Открытые вопросы владельцу

- Question: What is the formal go/no-go threshold for free closed beta?
- Why it matters: Gate B still has unchecked items.
- Suggested options: complete every Gate B item; allow limited beta with signed
  deferrals; hold until real-file matrix and restore rehearsal pass.
- Recommended default: require Gate B evidence or explicit owner deferral before
  inviting users.

- Question: What is the approved path for upload quarantine inspection?
- Why it matters: quarantine can involve suspicious user files and privacy risk.
- Suggested options: metadata-only admin view; explicit owner-only server
  process; no inspection during beta.
- Recommended default: metadata-only by default, raw file inspection only by
  explicit owner action outside normal agent tasks.

- Question: Should FB2 from GitHub issue #23 be explored after Gate B work?
- Why it matters: FB2 expands parser, fixture, dependency, QA and support scope
  beyond the approved TXT/DOCX/EPUB beta.
- Suggested options: keep deferred; run idea intake/spike later; reject for now.
- Recommended default: keep deferred until owner approval and Architect review.

- Question: When should paid beta planning start?
- Why it matters: payments/pricing are high-risk and Gate C is blocked.
- Suggested options: after Gate B; after first free beta cohort; postpone until
  support/refund policy exists.
- Recommended default: postpone paid beta until free beta evidence and owner
  support/refund decisions exist.

## 11. Инструкция для следующего агента

Перед началом любой задачи:

1. прочитай `AGENTS.md`;
2. прочитай `docs/HANDOFF.md`;
3. прочитай `docs/DECISIONS.md`;
4. прочитай `docs/CONTEXT_MAP.md`;
5. найди связанные тесты;
6. сделай маленький diff;
7. не меняй high-risk зоны без approve.

Правила:

- Не выдумывай completed work.
- Не называй фичу готовой, если нет подтверждения.
- Отделяй confirmed от assumption.
- Используй `TBD`, когда нужно решение человека.
- Используй `Unknown`, когда репозиторий не дает evidence.
- Не трактуй historical plans/specs как текущий roadmap без сверки с
  `DOCUMENT_INDEX.md` и active restart docs.
- Не меняй deployment, secrets, payments/pricing, auth/security, legal/privacy,
  user data handling, database migrations или production dependencies без
  explicit human approval.
- Для docs-only задач тесты можно не запускать, но это нужно прямо указать в
  отчете.
- Для code changes запускай focused tests и релевантные verification commands.
- Пиши так, чтобы следующий агент мог продолжить работу без догадок.
