# Roadmap

## 1. Назначение roadmap

Этот документ нужен, чтобы превращать текущее состояние FolioLoom в маленькие,
проверяемые задачи для GitHub Issues и будущего AI-оркестра. Он не заменяет
`docs/restart/release-gates.md`, а помогает выбрать порядок работы: что делать
сейчас, что делать дальше, что отложить и что не начинать без решения владельца.

Orchestrator Agent должен использовать roadmap как рабочую очередь верхнего
уровня: брать задачи из текущей фазы, дробить их на маленькие issues,
передавать рискованные изменения Architect Agent, а после завершения задач
просить Reviewer Agent проверить diff, тесты, scope и guardrails. Владелец
проекта должен обновлять этот файл после завершения фаз, изменения release
gates, изменения стадии проекта или явного go/no-go решения.

Confirmed facts должны оставаться отделены от Proposed, TBD и Unknown. Старые
планы из `docs/superpowers/plans/` нельзя считать текущим roadmap без сверки с
`CURRENT_PROJECT_STATE.md`, `DOCUMENT_INDEX.md` и restart-документами.

## 2. Текущая стадия проекта

Текущая стадия: **active development / working closed-beta foundation**.

Evidence:

- `README.md` прямо указывает `Product stage: Working closed-beta foundation`,
  следующий milestone `Free closed beta`, `Public production: Not ready`.
- `CURRENT_PROJECT_STATE.md` фиксирует, что проект уже не in-memory prototype:
  есть persistent jobs/work units, object storage, worker loop, admin console,
  Docker Compose deployment и backup/restore workflow.
- `docs/restart/release-gates.md` показывает, что Gate B для free closed beta
  еще не закрыт.
- `.github/workflows/checks.yml` exists, but current GitHub Actions run/pass
  status is **Unknown** unless checked on a PR/checks page.

Текущая предполагаемая roadmap-фаза: **Phase 0 -> Phase 1 transition**. Базовые
документы для AI-агентов уже существуют; Phase 0 теперь означает поддержание их
согласованности, устранение stale claims и подготовку маленьких задач для Gate B
evidence, а не создание документов с нуля.

## 3. Roadmap principles

- Сначала стабилизировать core flow: Telegram upload -> validation -> rights
  confirmation -> language/estimate -> explicit confirmation -> persistent
  job/work units -> worker/provider execution -> progress/cancel/status/history
  -> final or partial result.
- Делать маленькие PR с понятным scope и ближайшими тестами.
- Расширять тесты и release evidence до расширения продукта.
- Не делать production deployment без explicit human approval.
- Не расширять scope за пределы free closed beta без решения владельца.
- Не трогать high-risk зоны без review: payments/pricing, secrets, auth,
  deployment, database/state, retention/user data, legal/privacy/security,
  external provider behavior.
- Не ослаблять guardrails: rights confirmation, beta allowlist, cost caps, kill
  switch, SSH-tunnel-only admin, redaction of raw document text/prompts/keys.
- Не считать beta safety accounting платежным ledger.

## 4. Phase 0 - Documentation and agent readiness

Цель: поддерживать foundation для будущего AI-оркестра, чтобы агенты могли
безопасно разбивать работу, не выдумывать readiness и не прыгать в risky scope.

Tasks:

- Поддерживать `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `docs/HANDOFF.md`,
  `docs/DECISIONS.md`, `docs/CONTEXT_MAP.md`, `docs/QUALITY_GATES.md`,
  `docs/RISK_REGISTER.md`, `docs/RELEASE_CHECKLIST.md` и этот roadmap в
  согласованном состоянии.
- Синхронизировать `docs/QUALITY_GATES.md` с `docs/restart/release-gates.md`
  без заявления CI или release readiness без evidence.
- Синхронизировать `docs/RISK_REGISTER.md` с owner decisions, high-risk zones и
  текущими Gate B risks.
- Синхронизировать `docs/RELEASE_CHECKLIST.md` с free closed beta go/no-go
  requirements, Gate B evidence и human approval gates.
- Зафиксировать, какие старые specs/plans являются active, historical или
  superseded.

Acceptance criteria:

- Новый агент за 5-10 минут понимает текущую стадию, core flow, ограничения,
  текущую фазу и next tasks.
- Документы не обещают CI, production readiness, paid launch или новые форматы.
- Quality gates, risk register и release checklist ссылаются на confirmed
  evidence или явно используют TBD/Unknown.
- `docs/HANDOFF.md` и `docs/ROADMAP.md` обновлены после существенных изменений
  Phase 0 или перехода к следующей фазе.

## 5. Phase 1 - Stabilize core workflow

Цель: довести free closed-beta core workflow до проверяемого Gate B состояния
без добавления нового продуктового scope.

Core workflow по evidence из кода и документов:

- Telegram bot принимает TXT/DOCX/EPUB upload.
- Upload проходит validation и rights confirmation.
- Пользователь выбирает target language, получает estimate и подтверждает job.
- Backend создает persistent job/work units и хранит source/intermediate/result
  objects.
- Worker/scheduler выполняет work units через DeepSeek-compatible provider
  layer с capacity/cost guards.
- Пользователь видит progress, может cancel/resume/status/history/My Books и
  получает final или partial result.

Tasks:

- Completed 2026-05-14: issue
  [#30](https://github.com/ogirkoviylord/folioloom_main/issues/30) reliability
  split closed. PRs #36-#39 documented the root cause, added in-process
  automatic result delivery idempotency, paused admin bulk key tests during
  active translations/provider requests, and added worker/scheduler
  provider-failure regression coverage with safe retry metadata.
- Закрыть или явно отложить free preview before full translation. Confirmed
  progress: issues #51 and #52 are merged; PR #59 merged Telegram preview
  display and Continue/Back controls; the issue #54 implementation branch adds
  the preview-acceptance guard before full translation can start. Remaining
  blocker: Reviewer evidence and Gate B report.
- Проверить upload hardening/quarantine baseline для TXT/DOCX/EPUB и негативных
  fixtures.
- Проверить TTL cleanup/delete behavior для source/final/partial/quarantine
  только после approval, потому что это user data handling.
- Подтвердить cancel/resume/restart и worker/bot restart behavior release
  evidence.
- Подтвердить scheduler/runtime consistency и provider capacity behavior.
- Подготовить Gate B evidence report с pass/fail/deferred items.

Acceptance criteria:

- Gate B blockers либо закрыты, либо явно deferred с owner go/no-go note.
- Full translation не стартует без required confirmation path; free preview
  статус явно confirmed или deferred.
- Accepted jobs не теряются при worker/bot restart по release evidence.
- Provider failures дают safe user messaging и diagnosable metadata.
- Logs/admin не содержат raw document text, prompts, translations или keys.

Обязательные тесты:

- Focused tests для touched bot/backend/worker/provider/file-format зоны.
- Перед go/no-go: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Перед go/no-go: `PYTHONPATH=src python3 -m compileall src`.
- Перед go/no-go: `scripts/predeploy_check.sh`.
- Server smoke только в human-approved target environment.

Риски:

- Upload/retention/delete затрагивают user data handling.
- Scheduler/worker changes затрагивают durable state machine.
- Provider capacity changes могут увеличить cost/provider failure risk.
- Issue #30 reduced a known cancel/provider/admin reliability risk, but it does
  not complete broad cancel/resume/restart release evidence or durable
  cross-restart automatic delivery tracking.
- Free preview может изменить UX и backend job contract.

Что не входит в фазу:

- Paid beta, Telegram Stars/XTR, payment ledger, pricing changes.
- Public production, public admin exposure, public website/customer portal.
- Новые форматы кроме TXT/DOCX/EPUB.
- FB2 support from GitHub issue
  [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23); it is a
  deferred idea only until owner approval, Architect review and a separate
  agent-ready implementation issue exist.
- Большие переписывания scheduler, bot state или translation core.

## 6. Phase 2 - Improve observability and admin/debugging

Цель: дать owner/admin достаточно visibility для free closed beta без чтения
сырых логов и без утечки secrets/raw document text.

Tasks:

- Закрыть Alerts MVP для provider, queue/worker, disk, backup и failed jobs.
- Добавить или документировать backups visibility: последняя backup export,
  verify status, restore rehearsal artifact.
- Улучшить status tracking для jobs/work units, если release evidence покажет
  blind spots.
- Улучшить safe error reasons: provider auth/billing/rate-limit/timeout,
  parser rejection, quota/cap/kill switch.
- Описать support/debug workflow для owner: какие admin pages смотреть, какие
  scripts запускать, какие artifacts сохранять.
- Preserve the issue #30 admin guardrail: bulk provider key probes should wait
  until active translations and active provider requests return to 0.

Acceptance criteria:

- Owner может понять текущее состояние beta без просмотра raw runtime data.
- Error reasons actionable и безопасны для пользователя/admin.
- Backup/restore состояние видно через admin или documented owner report.
- Любые новые debug surfaces проходят redaction review.

Optional/TBD:

- Форма admin UX для backups visibility: admin page/card или owner runbook
  report. Требует решения владельца.

## 7. Phase 3 - Testing and reliability

Цель: сделать reliability проверяемой через unit, integration, regression,
real-file и smoke evidence.

Tasks:

- Сохранить broad unit coverage: сейчас `tests/` содержит 93 `test_*.py` файла.
- Выполнить real-file TXT/DOCX/EPUB matrix на authorized fixtures.
- Добавить release report с commit, env, commands, fixture manifest,
  pass/fail table и known failures.
- Проверить DOCX openability/visual QA.
- Проверить EPUBCheck или equivalent validation.
- Проверить negative fixtures: corrupt ZIP, wrong extension, oversize,
  traversal, zip-bomb-like, unsupported formats.
- Проверить regression scenarios: cancel, resume, worker restart, bot restart,
  provider failure, delete, backup/restore.
- Решить CI policy: current GitHub Actions workflow advisory/required status,
  and whether local gates remain required.

Acceptance criteria:

- Common verification commands проходят перед release go/no-go.
- Real-file matrix имеет сохраненный release artifact.
- Known failures явно перечислены и не маскируются как passed.
- CI pass status is not claimed unless visible PR/check evidence is inspected;
  local gates remain required until owner records a different policy.

## 8. Phase 4 - User experience and product polish

Цель: улучшить ясность Telegram/admin UX без расширения продукта за пределы
free closed beta.

Tasks:

- Проверить user-facing messages для upload rejection, rights confirmation,
  quota/cap/kill switch, provider failure, cancel/partial result.
- Уточнить onboarding для trusted beta users: что можно загружать, какие
  форматы поддержаны, какие ограничения beta действуют.
- Проверить My Books/history/status/resume/delete copy на понятность.
- Уточнить admin UX для costs/settings/live/provider health/alerts/backups.
- Обновлять docs после изменения workflow или release gates.

Acceptance criteria:

- Пользователь видит безопасные, понятные сообщения без stack traces/provider
  internals/raw text.
- Owner/admin видит operational state без раскрытия secrets.
- UX polish не добавляет payments, public signup, new formats или public admin.

## 9. Phase 5 - Release readiness

Цель: подготовить human go/no-go для free closed beta, а позже отдельно для
paid beta и public production.

Tasks:

- Создать free closed beta release checklist.
- Собрать Gate B evidence report.
- Запустить common verification commands.
- Получить server smoke evidence только на approved beta server.
- Проверить backup export и restore rehearsal artifact.
- Проверить monitoring/alerts минимального уровня.
- Провести privacy/security review для logs/admin/raw text/secrets.
- Подготовить rollback plan и owner support/debug workflow.
- Зафиксировать human approvals and deferrals.

Acceptance criteria:

- Gate B либо fully checked, либо имеет signed go/no-go note с явными deferrals.
- Public production и paid beta не объявляются готовыми.
- Deployment, payments, legal/privacy/security и user data decisions не меняются
  без explicit owner approval.

## 10. Later / deferred

Не делать сейчас:

- Public production launch.
- Production deployment без approval.
- Paid beta, Telegram Stars/XTR, payment ledger, refunds, reconciliation,
  support/refund policy.
- Stripe/YooKassa/card flow.
- Public website/customer portal, public signup, WhatsApp/Discord/public API.
- PDF/OCR/MOBI/FB2/batch ZIP/arbitrary parser.
- FB2 from GitHub issue
  [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23) without
  explicit owner approval, supported-subset decision, fixture rights basis,
  dependency review and Architect-approved safety/verification plan.
- Public admin exposure или изменение SSH-tunnel-only модели.
- Major rewrites of scheduler, bot runtime, provider layer or translation core.
- New external providers or user-facing provider/model picker.
- Complex automation beyond the current worker/scheduler needs.
- Legal/privacy/AUP/refund text without owner/counsel decision.
- Repo-wide ruff cleanup as a free closed-beta release blocker.

## 11. Backlog candidates

- Task: Maintain `docs/QUALITY_GATES.md` against current release gates.
  Phase: 0
  Priority: High
  Risk: Low
  Agent suitability: safe
  Suggested acceptance criteria: document maps Gate A/B/C/D to local checks,
  uses TBD/Unknown where evidence is missing, and does not invent CI or release
  readiness.

- Task: Maintain `docs/RISK_REGISTER.md`.
  Phase: 0
  Priority: High
  Risk: Medium
  Agent suitability: needs architect
  Suggested acceptance criteria: includes upload/retention, scheduler/state,
  provider/cost, admin/secrets, payments, deployment and legal/privacy risks
  with owner decisions marked TBD.

- Task: Maintain `docs/RELEASE_CHECKLIST.md` for free closed beta.
  Phase: 0
  Priority: High
  Risk: Medium
  Agent suitability: needs architect
  Suggested acceptance criteria: checklist references Gate B, common
  verification commands, server smoke, backup/restore, real-file matrix and
  human approvals.

- Task: Produce Gate B evidence report.
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: safe
  Suggested acceptance criteria: every Gate B item is pass/fail/deferred with
  evidence links and no production readiness claims.

- Task: Review free preview guard and record evidence.
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: reviewer
  Suggested acceptance criteria: issue #54 is reviewed with focused/full local
  verification evidence showing full translation cannot start before preview
  and explicit confirmation, or owner signs a deferral.

- Task: Verify upload hardening/quarantine baseline.
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: needs architect
  Suggested acceptance criteria: negative fixtures reject/quarantine safely,
  quarantined files never reach workers, logs/admin show metadata only.

- Task: Validate cancel/resume/restart behavior.
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: safe
  Suggested acceptance criteria: accepted jobs remain visible after bot/worker
  restart; cancel produces safe state and available partial result where
  expected.

- Task: Execute real-file TXT/DOCX/EPUB matrix.
  Phase: 3
  Priority: High
  Risk: Medium
  Agent suitability: safe
  Suggested acceptance criteria: release report records authorized fixtures,
  commands, pass/fail results, DOCX openability notes and EPUB validation.

- Task: Add Alerts MVP or document owner report alternative.
  Phase: 2
  Priority: Medium
  Risk: Medium
  Agent suitability: needs architect
  Suggested acceptance criteria: owner can see provider, queue/worker, disk,
  backup and failed-job alerts without raw text/secrets.

- Task: Decide CI policy.
  Phase: 3
  Priority: Medium
  Risk: Medium
  Agent suitability: needs human approval
  Suggested acceptance criteria: owner chooses whether the existing GitHub
  Actions workflow is advisory or required, and whether to expand it; docs keep
  run/pass status Unknown until PR/check evidence exists.

## 12. How Orchestrator should use this roadmap

- Читать `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `docs/HANDOFF.md`,
  `docs/DECISIONS.md`, `docs/CONTEXT_MAP.md` и этот файл перед планированием.
- Брать задачи из текущей фазы: сейчас Phase 0 -> Phase 1 transition.
- Не прыгать в Later / deferred без explicit owner approval.
- Дробить backlog candidates на маленькие issues с evidence, tests,
  acceptance criteria и risk label.
- Передавать risky tasks Architect Agent до implementation.
- Передавать focused implementation Implementer Agent с узким file scope.
- Передавать Reviewer Agent проверку diff, tests, release gates and guardrails.
- После завершения фазы обновлять `docs/HANDOFF.md` и `docs/ROADMAP.md`.
- Если задача затрагивает payments, deployment, auth, secrets, database/state,
  retention/user data, legal/privacy/security или external provider behavior,
  сначала получить review и нужный human approval.
