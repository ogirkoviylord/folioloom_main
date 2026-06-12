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
- `.github/workflows/checks.yml` exists. Owner decision on 2026-05-17:
  GitHub Actions Python checks are advisory for now, local gates remain
  required, and current run/pass status is **Unknown** unless checked on a
  PR/checks page.

Текущая предполагаемая roadmap-фаза: **Phase 0 -> Phase 1 transition**. Базовые
документы для AI-агентов уже существуют; Phase 0 теперь означает поддержание их
согласованности, устранение stale claims и подготовку маленьких задач для Gate B
evidence, а не создание документов с нуля.

## 3. Roadmap principles

- Сначала стабилизировать core flow: Telegram upload -> validation -> rights
  confirmation -> translation mode -> language/estimate -> explicit
  confirmation -> persistent job/work units -> worker/provider execution ->
  progress/cancel/status/history -> final or partial result.
- Делать маленькие PR с понятным scope и ближайшими тестами.
- Расширять тесты и release evidence до расширения продукта.
- Не делать production deployment без explicit human approval.
- Не расширять scope за пределы free closed beta без решения владельца.
- Не трогать high-risk зоны без review: payments/pricing, secrets, auth,
  deployment, database/state, retention/user data, legal/privacy/security,
  external provider behavior.
- Не ослаблять guardrails: rights confirmation, beta allowlist, cost caps, kill
  switch, SSH-tunnel-only admin, secret/prompt/key redaction and approved
  raw-text handling. Dedicated owner-only text diagnostics and downloaded full
  diagnostic archives are accepted exceptions. Downloaded full diagnostic
  archives may also include run-scoped `provider_io_diagnostics.jsonl` with
  exact provider request/response bodies for incident debugging, excluding
  provider `Authorization` headers and API keys. Telemetry, normal admin pages,
  APIs and support artifacts remain metadata-only/redacted.
- Не считать beta safety accounting платежным ledger.

## 4. Phase 0 - Documentation and agent readiness

Цель: поддерживать foundation для будущего AI-оркестра, чтобы агенты могли
безопасно разбивать работу, не выдумывать readiness и не прыгать в risky scope.

Tasks:

- Поддерживать `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `docs/HANDOFF.md`,
  `docs/AGENT_SKILL_ROUTING.md`, `docs/DECISIONS.md`,
  `docs/CONTEXT_MAP.md`, `docs/QUALITY_GATES.md`,
  `docs/RISK_REGISTER.md`, `docs/RELEASE_CHECKLIST.md` и этот roadmap в
  согласованном состоянии.
- Поддерживать Skill Dispatch Contract: repo-level skills должны выбирать
  минимальный безопасный route, фиксировать approval status и не обходить
  high-risk gates через specialized/global skills.
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
- Новый агент применяет Skill Dispatch Contract до выбора skill, а Reviewer
  может проверить routing receipt в финальном отчете.
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
- Пользователь выбирает translation mode and target language, получает estimate
  и подтверждает job.
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
- Completed 2026-05-16: free preview before full translation is evidenced for
  the implementation slice. PRs #57/#58/#59/#61/#67 are merged, issue #56 local
  verification passed focused preview/bot/service tests, full unittest suite and
  compileall plus `scripts/predeploy_check.sh`, and
  `docs/restart/release-gates.md` checks only the preview item. Gate B overall
  remains incomplete.
- Wire translation modes through the closed-beta flow in small follow-up slices.
  Issues #44, #45, #46 and #55 are merged for mode selection, metadata,
  DOCX routing/profile behavior and preview-mode propagation.
- Completed 2026-05-28: issue #73 verifies upload hardening/quarantine
  baseline for local synthetic TXT/DOCX/EPUB fixtures. Negative fixtures cover
  unsupported extensions, wrong extension/content mismatch, invalid/binary TXT,
  corrupt ZIP, traversal/absolute paths, archive size/count/compression limits,
  missing expected structure and executable-looking embedded paths. This does
  not close TTL/quarantine cleanup, real-file QA, approved beta-server smoke or
  full Gate B readiness.
- Completed 2026-05-28: issue #78 verifies release-wide logs/admin raw-text
  redaction with local synthetic evidence. The review found an admin
  translation-log archive leak risk recorded as issue #117, then fixed the run
  artifact redaction path so event payloads and error fields are redacted before
  archive generation. Regression tests inspect archive contents for raw
  source/translated snippets, prompt text, API-key-like strings, provider key
  identifiers and traceback markers. This does not close real-file matrix,
  beta-server smoke, backup/restore or full Gate B readiness.
- Approved 2026-05-28 and closed as a first slice on 2026-05-30: duplicate
  upload / retry architecture for issues #120-#125 uses a no-schema first
  implementation. Work order is #121 fresh
  translate-again attempt semantics before #123 duplicate upload UX, so the bot
  does not show a `translate again` action before the action is implemented.
  The first duplicate lookup is same-user only, scans at most `100` same-user
  persistent jobs by source metadata, keeps resume My Books-only, and treats
  free retry/retranslate as beta-safety accounting rather than paid billing.
  Schema/state changes, durable indexed duplicate keys, concurrent duplicate
  work, TTL cleanup and runtime data operations require separate approval.
- Completed and merged 2026-05-29: issue #121 implements fresh attempt identity
  for repeated same-document translation without schema changes. Repeated
  pending attempts get distinct preview reservation ids; repeated persistent
  translations create distinct job ids and keep old/new My Books history and
  result access. Same-pending duplicate preview protection remains in place,
  rights confirmation remains required, and beta-safety preview/job accounting
  is reserved/consumed per attempt. This does not implement #123 duplicate
  upload UX, duplicate lookup, durable indexes, concurrent duplicate work,
  TTL cleanup, paid retries or release readiness.
- Completed and merged 2026-05-30: issue #123 implements the first duplicate
  upload UX slice without schema changes. After rights confirmation,
  translation mode and target language selection, the bot performs a bounded
  same-user metadata scan before preview/provider work. Ready duplicates offer
  existing download or fresh translate-again, active duplicates do not allow
  concurrent translate-again, and recoverable duplicates keep resume in My
  Books rather than the upload prompt. This does not implement durable duplicate
  indexes, schema/state changes, upload-flow resume, TTL cleanup, paid retry
  policy, deployment or release readiness.
- Completed and merged 2026-05-30: issue #125 keeps resume controls My Books-only
  for recoverable translations without schema changes. My Books detail shows
  `Continue Translation` only for architecture-approved recoverable statuses
  when the stored source object is available for backend resume. Duplicate
  upload choices do not show resume; partial duplicate results offer partial
  download plus an open-existing/My Books path. This does not close broad Gate B
  cancel/resume/restart release evidence.
- Closed 2026-05-30: umbrella issue #120 is complete for the approved first
  slice. Child issues #122, #124, #121, #123 and #125 are closed; PRs #126-#130
  are merged and their visible GitHub `Python checks` passed. Future robust
  duplicate indexing, schema/state changes, concurrent duplicate work,
  upload-flow resume, TTL/delete cleanup and paid retry policy remain separate
  tasks requiring explicit approval where applicable.
- Добавить local malware/AV scanning gate как часть upload hardening: quarantine
  first, scan before parsing, fail closed for beta scanner errors unless owner
  approves otherwise, and keep public VirusTotal-style submission out of the
  default path.
- Проверить TTL cleanup/delete behavior для source/final/partial/quarantine
  только после approval, потому что это user data handling.
- Подтвердить cancel/resume/restart и worker/bot restart behavior release
  evidence.
- Подтвердить scheduler/runtime consistency и provider capacity behavior.
- Подготовить Gate B evidence report с pass/fail/deferred items.

Acceptance criteria:

- Gate B blockers либо закрыты, либо явно deferred с owner go/no-go note.
- Full translation не стартует без required confirmation path; free preview is
  confirmed for the implementation slice, while broader Gate B readiness remains
  open.
- Accepted jobs не теряются при worker/bot restart по release evidence.
- Provider failures дают safe user messaging и diagnosable metadata.
- Logs/admin do not expose raw document text, prompts, translations or keys
  outside the approved owner-only diagnostics surfaces and full diagnostic
  downloads; telemetry, normal details, APIs and support artifacts remain
  redacted/metadata-only.

Обязательные тесты:

- Focused tests для touched bot/backend/worker/provider/file-format зоны.
- Перед go/no-go: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Перед go/no-go: `PYTHONPATH=src python3 -m compileall src`.
- Перед go/no-go: `scripts/predeploy_check.sh`.
- Server smoke только в human-approved target environment.

Риски:

- Upload/retention/delete затрагивают user data handling.
- Local malware/AV scanning затрагивает security, privacy, deployment,
  dependencies and runtime user-data boundaries; implementation requires
  Architect review and owner approval for deployment/new dependency slices.
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
- New committed future formats beyond TXT/DOCX/EPUB, including FB2 from GitHub
  issue [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23), until
  issue #208 prioritizes them and separate format-specific implementation
  issues are approved.
- Большие переписывания scheduler, bot state или translation core.

## 6. Phase 2 - Improve observability and admin/debugging

Цель: дать owner/admin достаточно visibility для free closed beta. During
pre-release development, owner-approved raw provider diagnostics may capture the
full analysis context for translation/provider failures, but secrets must remain
excluded and release-version behavior must be redesigned or re-approved before
free beta/public release.

Tasks:

- Закрыть Alerts MVP для provider, queue/worker, disk, backup и failed jobs
  через metadata-only owner runbook/report for Gate B; admin UI later.
- Добавить backups visibility в owner runbook/report: последняя backup export,
  verify status, restore rehearsal artifact. Admin UI is a later follow-up.
- Улучшить status tracking для jobs/work units, если release evidence покажет
  blind spots.
- Улучшить safe error reasons: provider auth/billing/rate-limit/timeout,
  parser rejection, quota/cap/kill switch.
- Add pre-release automatic raw provider diagnostics capture for owner-only
  analysis of crashes and translation bugs: source work-unit text, prompt
  bodies, provider user payloads, raw provider outputs, repair prompts,
  output-contract validation details and related job/work-unit state. This must
  stay out of release-version telemetry/support/legal/privacy claims until the
  owner revisits retention, consent, redaction and deletion behavior.
- Treat the first owner-approved Beta Operations Console redesign stack as
  implemented by PR #160 and closed through #145-#152. Follow-up admin work
  should be scoped separately, including raw prompt diagnostics, Alerts/Backups
  visibility and any new release-evidence surfaces.
- Treat issue #165 as a docs-only Book/Manuscript MVP contract: structure
  preservation plus clean translation, with format-specific TXT/DOCX/EPUB
  expectations and no release-readiness claims.
- Описать support/debug workflow для owner: какие admin pages смотреть, какие
  scripts запускать, какие artifacts сохранять.
- Preserve the issue #30 admin guardrail: bulk provider key probes should wait
  until active translations and active provider requests return to 0.

Acceptance criteria:

- Owner может понять текущее состояние beta; during development the owner may
  inspect broad raw provider diagnostics, while release-version raw capture
  remains gated by a required pre-release review.
- Error reasons actionable и безопасны для пользователя/admin.
- Owner can open one failed translation trace and see safe user/upload/job/run,
  provider/key and failure-category evidence without hunting through multiple
  log-like pages. Confirmed by the PR #160 admin redesign stack.
- Backup/restore состояние видно через admin или documented owner report.
- Любые новые debug surfaces проходят redaction review. Pre-release raw capture
  follows the 2026-06-06 owner decision; release-version raw capture remains
  TBD until Release Readiness review.

Later:

- Admin UI для backups/alerts visibility remains a follow-up. Issue #71 chose
  metadata-only owner report for Gate B so new bot features do not force broad
  admin console rewrites. The first 2026-05-31 Beta Operations Console stack is
  implemented by PR #160, but Gate B evidence remains separate until
  implemented and verified.
- Future book/manuscript work is split out of #165: terminology/name policy
  and complex glossary/profile architecture (#204), read-only glossary viewer
  (#205), editable glossary workflow (#206), release-version analytics
  file-use and consent policy (#207), future format prioritization (#208) and
  stricter quality rubric (#209). Owner direction on 2026-06-12 makes #204 a
  complex architecture/discovery item: glossary-by-default for books,
  `book_translation_profile`, DeepSeek Pro roles, translation contract
  snapshots, profile-specific rules and broad pre-release diagnostics must be
  designed before runtime implementation.

## 7. Phase 3 - Testing and reliability

Цель: сделать reliability проверяемой через unit, integration, regression,
real-file и smoke evidence.

Tasks:

- Сохранить broad unit coverage: сейчас `tests/` содержит 93 `test_*.py` файла.
- Выполнить real-file TXT/DOCX/EPUB matrix на authorized fixtures.
- Добавить release report с commit, env, commands, fixture manifest,
  pass/fail table и known failures.
- Проверить DOCX openability/visual QA.
- Проверить EPUB через local/offline EPUBCheck. Online validators are not
  approved; EPUBCheck is a release verification tool, not a production
  dependency.
- Проверить negative fixtures: corrupt ZIP, wrong extension, oversize,
  traversal, zip-bomb-like, unsupported formats.
- Проверить regression scenarios: cancel, resume, worker restart, bot restart,
  provider failure, delete, backup/restore.
- Preserve CI policy: current GitHub Actions workflow is advisory for now,
  local gates remain required, and CI pass status must not be claimed without
  visible PR/check evidence.

Acceptance criteria:

- Common verification commands проходят перед release go/no-go.
- Real-file matrix имеет сохраненный release artifact.
- Known failures явно перечислены и не маскируются как passed.
- CI pass status is not claimed unless visible PR/check evidence is inspected;
  local gates remain required.

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
- Owner/admin видит operational state без раскрытия secrets; raw
  source/translated text is available through approved owner-only diagnostics
  and full diagnostic downloads for incident debugging.
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
- Immediate PDF/OCR/MOBI/FB2/batch ZIP/arbitrary parser implementation.
- FB2 from GitHub issue
  [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23) and other
  committed future formats without a format-specific approved implementation
  issue, supported-subset decision, fixture rights basis, dependency review and
  Architect-approved safety/verification plan.
- Public admin exposure или изменение SSH-tunnel-only модели.
- Major rewrites of scheduler, bot runtime, provider layer or translation core.
- New external providers or user-facing provider/model picker.
- Complex automation beyond the current worker/scheduler needs.
- Legal/privacy/AUP/refund text without owner/counsel decision.
- Book/manuscript future scope without separate issues: terminology/name
  controls, complex glossary/profile architecture, glossary viewer/editor,
  stricter literary/editorial quality rubric, user analytics consent/release
  policy and new formats beyond TXT/DOCX/EPUB.
- New format implementation beyond TXT/DOCX/EPUB. Committed future format
  families are tracked as post-MVP roadmap scope: RTF (#4), FB2 (#23), PDF/OCR,
  HTML/HTM, ODT, legacy DOC, MOBI, AZW3/KPF and image-heavy CBZ/CBR/DJVU.
  Issue #208 owns prioritization and issue breakdown; implementation requires
  separate format-specific approval and architecture review.
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

- Task: Prioritize committed future document/book formats (#208).
  Phase: Later
  Priority: Medium
  Risk: High
  Agent suitability: needs idea intake and architecture review
  Suggested acceptance criteria: rank RTF (#4), FB2 (#23), PDF/OCR, HTML/HTM,
  ODT, legacy DOC, MOBI, AZW3/KPF and CBZ/CBR/DJVU by user value, parser and
  resource risk, fixture rights basis, dependency/deployment impact,
  privacy/security surface and QA/release burden; produce a format-specific
  issue breakdown and do not implement any format in #208.

- Task: Design complex book glossary/profile architecture (#204).
  Phase: Later
  Priority: Medium
  Risk: High
  Agent suitability: needs architecture review
  Suggested acceptance criteria: produce a no-code architecture package for
  glossary-by-default book routes, `book_translation_profile`, DeepSeek Pro
  role graph/contracts, schema/enums, evidence/confidence policy,
  profile-specific rules, translation contract snapshot boundary,
  diagnostics/logging scope, failure/fallback behavior, RU/UK morphology TBD
  handling and implementation issue split. Do not add runtime behavior,
  persistence/schema, provider config, admin UI, deployment or release/privacy
  claims in #204.
  Status: issues #404 / #204A, #405 / #204B, #406 / #204C, #407 / #204D,
  #408 / #204E, #409 / #204F, #410 / #204G, #411 / #204H, #412 / #204I,
  #413 / #204J, #414 / #204K, #415 / #204L and #416 / #204M
  produced the no-code architecture package, local glossary contracts,
  deterministic scanner over existing TXT/DOCX/EPUB adapter-plan fixtures,
  local book profile detector/rule contract, fake-output DeepSeek Pro role JSON
  validators, a local deterministic translation contract snapshot builder, a
  local per-work-unit glossary subset selector, optional compact
  glossary/profile cache/policy signature context and a design-only
  owner-only glossary/profile diagnostics sidecar schema/boundary package.
  #413 added a standalone bounded spike runner and a metadata-only
  provider-backed spike report. The live run made 6 approved calls: profile
  advisor outputs validated on all three fixtures, glossary editor output
  validated only on the small sample fixture, large-fixture glossary editor
  outputs failed `invalid_json` after provider `length` finishes, and observed
  provider token usage exceeded the approved cap. Do not integrate runtime
  DeepSeek Pro roles yet. #414-#416 were then used to test whether the
  glossary-editor path could be made smaller, packetized and locally
  validated before runtime integration. #414 added a local deterministic chunked
  glossary-editor packetizer with compact reference payloads, stable packet
  ids/signatures, evidence and token-budget caps, degradation/skipped metadata
  and fixture coverage over the three #413 TXT samples. #415 added local
  fake-output validators and deterministic merge/adjudication for one
  `GlossaryEditorPacket` at a time, treating invalid chunks, duplicates,
  target/alias conflicts and low-confidence semantic claims as findings rather
  than trusted glossary facts. #416 added a standalone bounded chunked
  DeepSeek Pro glossary-editor spike runner and metadata-only report. The live
  run made 3 approved calls over the first READY packet per approved fixture,
  observed 16973 provider tokens, validated only the small sample packet, and
  recorded two invalid larger-fixture outputs due to missing evidence refs. The
  recommendation is to pivot or iterate chunk prompt/evidence behavior before
  runtime integration. Issue #430 / #204N tightens that local fake-output
  evidence contract by adding a compact `evidence_contract` to the chunked
  prompt, requiring non-empty resolvable `evidence_refs`, and proving missing
  refs stay structured validation/merge blockers. Issue #432 / #204P adds a
  local metadata-only evaluator for schema validity, evidence-ref coverage,
  invalid chunk rate, blocker/warning findings, duplicate/conflict rate, budget
  overrun, `needs_review` rate and provider token-cap evidence. These gates
  help decide when to run a bounded provider retry and when to proceed to
  no-code runtime architecture review. Issue #433 / #204Q adds the no-code
  runtime integration architecture boundary for job planning, work-unit
  selection, prompt policy, cache/signature handling, diagnostics, fallback
  behavior, readiness gates and follow-up order. This is architecture evidence,
  not a production glossary or runtime translation feature. Any further live
  spike needs fresh exact approval, and any runtime prompt/cache/storage/admin/
  retention implementation needs separate owner approval. Issue #431 / #204O
  ran the approved bounded retry after #430; the live run made 3 calls,
  observed 19592 provider tokens, validated only `sample_book.en.txt`, and
  recorded invalid JSON for the RU/UK regression packets because both ended
  with provider `finish_reason=length`. The recommendation remains
  pivot/iterate prompt/packet/completion budgeting before runtime integration.

- Task: Produce Gate B evidence report.
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: safe
  Suggested acceptance criteria: every Gate B item is pass/fail/deferred with
  evidence links and no production readiness claims.

- Task: Verify upload hardening/quarantine baseline.
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: done 2026-05-28 by issue #73
  Suggested acceptance criteria: negative fixtures reject/quarantine safely,
  quarantined files never reach workers, logs/admin show metadata only.

- Task: Design local malware/AV scanning gate for uploads
  ([#91](https://github.com/ogirkoviylord/folioloom_main/issues/91)).
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: needs architect and human approval
  Suggested acceptance criteria: design records scanner contract, verdict
  taxonomy, fail-closed beta behavior, quarantine state transitions, metadata
  redaction rules, ClamAV/local-scanner deployment implications and explicit
  out-of-scope default public VirusTotal-style submission.

- Task: Implement scanner contract and fake scanner tests
  ([#92](https://github.com/ogirkoviylord/folioloom_main/issues/92)).
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: needs review
  Suggested acceptance criteria: upload flow can require a scanner verdict
  before accepted storage/parser/worker access; tests prove clean/infected/error
  verdicts route safely without adding production dependencies or deployment
  changes.

- Task: Reconcile remaining AV issues around Upload Safety Ledger
  ([#101](https://github.com/ogirkoviylord/folioloom_main/issues/101)).
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: safe docs-only, needs review
  Suggested acceptance criteria: #93, #94 and #95 explicitly depend on the
  Upload Safety Ledger foundation before ClamAV, upload-flow wiring and Gate B
  evidence; docs keep malware scanning and Gate B readiness unimplemented until
  verified; metadata-only, fail-closed beta behavior and no default public
  VirusTotal-style submission remain intact.

- Task: Add local ClamAV scanner adapter after approval
  ([#93](https://github.com/ogirkoviylord/folioloom_main/issues/93)).
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: needs tests and review
  Dependency: Upload Safety Ledger foundation from #101/#102 and owner approval
  recorded in #93.
  Suggested acceptance criteria: adapter supports local/internal `clamd`
  `INSTREAM` scanning through the existing scanner contract, requires no shared
  quarantine volumes, adds no new Python production dependency, records safe
  scanner metadata, handles timeout/unavailable/malformed/error fail-closed for
  beta, passes fake `clamd` EICAR/equivalent response tests and does not expose
  raw document text, raw scanner output, object keys, paths or secrets.

- Task: Add internal clamd service for beta runtime
  ([#109](https://github.com/ogirkoviylord/folioloom_main/issues/109)).
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: needs architect and human approval
  Dependency: #93 adapter lands first.
  Suggested acceptance criteria: internal-only `clamd` Docker Compose/runtime
  service is not publicly exposed, app runtime reaches it through approved
  config, scanner health/signature visibility is metadata-only,
  resource/concurrency/timeout safeguards are defined, EICAR/equivalent smoke
  evidence is recorded in an approved environment, and no real user data or
  runtime `var/` operation occurs without exact-run owner approval.

- Task: Wire scanner verdicts into Telegram upload flow
  ([#94](https://github.com/ogirkoviylord/folioloom_main/issues/94)).
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: needs architect and review
  Dependency: Upload Safety Ledger foundation from #101 and, for real local
  scanner behavior, #93 after required approvals.
  Suggested acceptance criteria: clean ledger-backed verdicts allow the upload
  flow to continue; infected, scanner timeout/unavailable/error and unscanned
  uploads fail closed before estimate, preview, persistent jobs, parser or
  worker access; user/admin/log output remains metadata-only.

- Task: Add malware scanning release evidence for Gate B
  ([#95](https://github.com/ogirkoviylord/folioloom_main/issues/95)).
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: release-scoped docs/verification, needs review
  Dependency: Upload Safety Ledger foundation from #101/#102, upload-flow wiring
  from #94, adapter implementation from #93 and runtime evidence from #109 for
  full server/runtime evidence, unless an explicit owner-approved deferral
  exists.
  Status: issue #95 metadata-only local evidence is recorded in
  `docs/restart/gate-b-evidence-report.md` on the PR branch; it is not a full
  Gate B, free beta, public production or deployment readiness claim.
  Suggested acceptance criteria: evidence records clean, infected/EICAR,
  timeout/unavailable/error and unscanned paths with commands and metadata-only
  artifacts; it does not claim broader Gate B or production readiness.

- Task: Validate cancel/resume/restart behavior.
  Phase: 1
  Priority: High
  Risk: Medium
  Agent suitability: safe
  Suggested acceptance criteria: accepted jobs remain visible after bot/worker
  restart; cancel produces safe state and available partial result where
  expected.

- Task: Let users download available fragments from crashed translations.
  Phase: 1
  Priority: High
  Risk: High
  Agent suitability: needs architect and review
  Suggested acceptance criteria: when a persistent job fails or is interrupted
  after translating some work units, Telegram/My Books can offer a clearly
  labeled partial/crashed-result download only if safe assembly is possible;
  the user-facing copy explains that the file is incomplete; beta-safety
  accounting is not treated as paid billing; source/intermediate/final storage,
  retry/resume state, duplicate-upload behavior and raw-text/admin redaction
  boundaries remain unchanged unless separately approved and tested.

- Task: Execute real-file TXT/DOCX/EPUB matrix.
  Phase: 3
  Priority: High
  Risk: Medium
  Agent suitability: safe
  Suggested acceptance criteria: release report records authorized fixtures,
  commands, pass/fail results, DOCX openability notes and local/offline
  EPUBCheck validation.

- Task: Build internal/dev before-after reader for approved fixtures.
  Phase: 3
  Priority: Medium
  Risk: Medium
  Agent suitability: needs architect first slice, then focused implementer
  Status: issue #181 first TXT local HTML report slice is ready for review in
  PR #185 on branch `codex/issue-181-internal-reader-txt-report`; issue #182
  generic semantic block mapping slice is locally verified on stacked branch
  `codex/issue-182-generic-reader-block-model`; issue #183 DOCX renderer spike
  recommendation is recorded on branch `codex/issue-183-docx-renderer-spike`;
  issue #184 EPUB renderer spike recommendation is recorded on branch
  `codex/issue-184-epub-renderer-spike`; issue #189 EPUB local report slice is
  locally verified on branch `codex/issue-189-epub-reader-report`; issue #191
  EPUB sandboxed XHTML preview slice is locally verified on branch
  `codex/issue-191-epub-xhtml-preview`; issue #193 EPUB preview resource
  inlining slice is locally verified on branch
  `codex/issue-193-epub-preview-resources`; issue #195 DOCX structure preview
  slice is locally verified on branch `codex/issue-195-docx-structure-preview`;
  issue #197 format auto-detection CLI slice is locally verified on branch
  `codex/issue-197-reader-format-auto`; issue #199 owner-only internal admin UI
  slice is in progress on branch `codex/issue-internal-reader-ui`; run-log
  Translation Reader v2 is locally verified on branch
  `codex/internal-reader-v2` as an owner-only diagnostic surface linked from
  logs/details/Text diagnostics, with no raw-text API/archive expansion. Issue
  [#214](https://github.com/ogirkoviylord/folioloom_main/issues/214) begins the
  first run-log Reader/Text Diagnostics controls slice on branch
  `codex/issue-214-reader-controls`: opt-in invisible-character markers,
  logical sequence navigation, jump-by-sequence and reader sync-scroll toggle.
  Issue
  [#216](https://github.com/ogirkoviylord/folioloom_main/issues/216) begins the
  next current-window QA aids slice on branch
  `codex/issue-216-reader-qa-aids`: search with safe highlighting, reader QA
  counts and a metadata-only minimap for loaded work units. Issue
  [#218](https://github.com/ogirkoviylord/folioloom_main/issues/218) begins the
  first layout/indent diagnostics slice on branch
  `codex/issue-218-reader-indent-diagnostics`: literal indentation evidence,
  `Unknown` style metadata and opt-in editorial first-line indent preview.
  Issue
  [#220](https://github.com/ogirkoviylord/folioloom_main/issues/220) begins the
  first logical-page navigation slice on branch
  `codex/issue-220-reader-logical-pages`: logical `page` query support, current
  page/sequence-range status and page-size controls over bounded work-unit
  windows.
  Issue
  [#222](https://github.com/ogirkoviylord/folioloom_main/issues/222) begins the
  first current-window QA filter slice on branch
  `codex/issue-222-reader-qa-filters`: filter controls for already-computed
  empty source, missing translation, length mismatch and literal indent signals.
  Issue
  [#224](https://github.com/ogirkoviylord/folioloom_main/issues/224) begins the
  first per-work-unit metrics slice on branch
  `codex/issue-224-reader-block-metrics`: source/translation character counts
  and translation/source length ratio for visible work units.
  Issue
  [#226](https://github.com/ogirkoviylord/folioloom_main/issues/226) begins the
  first paragraph-structure diagnostics slice on branch
  `codex/issue-226-reader-paragraph-diagnostics`: source/translation line
  counts, blank-line counts, `paragraph_mismatch` QA flag/filter and Reader QA
  summary count for visible work units only.
  Issue
  [#228](https://github.com/ogirkoviylord/folioloom_main/issues/228) begins the
  first QA issue navigation slice on branch
  `codex/issue-228-reader-qa-navigation`: a Reader-only current-window issue
  rail linking existing QA flags to comparison block anchors.
  Issue
  [#230](https://github.com/ogirkoviylord/folioloom_main/issues/230) begins the
  first Reader keyboard navigation slice on branch
  `codex/issue-230-reader-keyboard-navigation`: ArrowLeft/ArrowRight navigation
  to the existing Previous/Next logical window URLs, ignoring interactive form
  controls.
  Issue
  [#232](https://github.com/ogirkoviylord/folioloom_main/issues/232) begins the
  first Reader sticky position bar slice on branch
  `codex/issue-232-reader-sticky-position`: a Reader-only sticky status bar for
  current logical page, sequence range and active query/toggle states.
  Issue
  [#234](https://github.com/ogirkoviylord/folioloom_main/issues/234) begins the
  first Reader QA issue step-controls slice on branch
  `codex/issue-234-reader-qa-step-controls`: Reader-only Previous issue /
  Next issue controls that navigate through existing QA issue anchors in the
  currently loaded work-unit window.
  Issue
  [#236](https://github.com/ogirkoviylord/folioloom_main/issues/236) begins the
  first Reader active QA highlight slice on branch
  `codex/issue-236-reader-active-qa-highlight`: active issue-link state plus
  matching original/translation block highlight for the selected current-window
  QA issue.
  Issue
  [#238](https://github.com/ogirkoviylord/folioloom_main/issues/238) begins the
  first Reader QA issue progress slice on branch
  `codex/issue-238-reader-qa-progress`: a current-window QA progress chip that
  shows the visible issue total and selected `Issue X of N` state.
  Issue
  [#240](https://github.com/ogirkoviylord/folioloom_main/issues/240) begins the
  first Reader search-hit navigation slice on branch
  `codex/issue-240-reader-search-hit-navigation`: Reader-only Previous hit /
  Next hit controls and selected `Hit X of N` state for already rendered
  current-window search highlights.
  Issue
  [#242](https://github.com/ogirkoviylord/folioloom_main/issues/242) begins the
  first Reader search-hit row filter slice on branch
  `codex/issue-242-reader-search-hit-filter`: a Reader-only `search_hits=1`
  mode that narrows the already loaded work-unit window to rows containing the
  active source/translation search query while leaving Text Diagnostics
  unchanged.
  Issue
  [#244](https://github.com/ogirkoviylord/folioloom_main/issues/244) begins the
  first Reader pane focus slice on branch
  `codex/issue-244-reader-pane-focus-mode`: Reader-only split,
  original-focus and translation-focus layout modes for the current before/after
  view.
  Issue
  [#246](https://github.com/ogirkoviylord/folioloom_main/issues/246) begins the
  first all-issues QA filter slice on branch
  `codex/issue-246-reader-all-issues-filter`: a shared owner-only `qa=issues`
  filter that keeps current-window rows with any existing QA flag or
  literal-indent layout flag in Reader and Text Diagnostics.
  Issue
  [#248](https://github.com/ogirkoviylord/folioloom_main/issues/248) begins the
  first Reader layout issue navigation slice on branch
  `codex/issue-248-reader-layout-issue-nav`: existing literal-indent layout
  flags participate in current-window issue navigation, minimap warning state
  and block warning styling.
  Issue
  [#250](https://github.com/ogirkoviylord/folioloom_main/issues/250) begins the
  Reader sync-scroll drift bugfix on branch
  `codex/issue-250-reader-scroll-drift`: harden synced pane scrolling so
  programmatic scroll events do not feed back into the pane the owner is
  actively scrolling.
  Issue
  [#252](https://github.com/ogirkoviylord/folioloom_main/issues/252) begins the
  Reader QA/Layout metric filter-link slice on branch
  `codex/issue-252-reader-qa-metric-links`: make existing current-window
  Reader QA/Layout metric cards navigate to the matching Reader filters while
  preserving search, pane, special-character, sync, indent-preview and
  pagination context.
  Issue
  [#254](https://github.com/ogirkoviylord/folioloom_main/issues/254) begins the
  Reader block outline slice on branch
  `codex/issue-254-reader-block-outline`: add a metadata-only current-window
  outline for all visible work units so the owner can navigate every loaded
  block, not only QA issue rows.
  Issue
  [#256](https://github.com/ogirkoviylord/folioloom_main/issues/256) begins the
  active Reader outline navigation slice on branch
  `codex/issue-256-reader-active-outline`: make outline clicks and QA issue
  navigation keep the selected outline entry and matching original/translation
  blocks visibly active.
  Issue
  [#258](https://github.com/ogirkoviylord/folioloom_main/issues/258) begins the
  client-only Reader review marks slice on branch
  `codex/issue-258-reader-review-marks`: add current-page DOM-only mark controls
  for visible original/translation work-unit pairs so the owner can temporarily
  tag blocks as needs-review, OK or ignored during side-by-side review.
  Issue
  [#260](https://github.com/ogirkoviylord/folioloom_main/issues/260) begins the
  client-side Reader review mark filter slice on branch
  `codex/issue-260-reader-review-mark-filters`: add current-page counts and
  DOM-only filters for temporary needs-review, OK and ignored marks.
  Issue
  [#262](https://github.com/ogirkoviylord/folioloom_main/issues/262) begins the
  client-side Reader review mark navigation slice on branch
  `codex/issue-262-reader-review-mark-navigation`: add current-page Previous
  mark / Next mark stepping for temporary review marks.
  Issue
  [#264](https://github.com/ogirkoviylord/folioloom_main/issues/264) begins the
  client-side Reader unmarked review filter slice on branch
  `codex/issue-264-reader-unmarked-review-filter`: add current-page marked and
  unmarked completion counts plus an Unmarked DOM-only filter.
  Issue
  [#266](https://github.com/ogirkoviylord/folioloom_main/issues/266) begins the
  client-side Reader review mark keyboard shortcut slice on branch
  `codex/issue-266-reader-review-hotkeys`: add current-page numeric shortcuts
  for temporary review marks without changing existing ArrowLeft/ArrowRight
  logical page navigation.
  Issue
  [#268](https://github.com/ogirkoviylord/folioloom_main/issues/268) resumes one
  narrow owner-approved persistence slice on branch
  `codex/issue-268-reader-persisted-marks`: save marked Reader work-unit
  excerpts, including both original/source and translated text, in a run-scoped
  owner-only raw diagnostic sidecar while keeping normal details and APIs
  redacted. Downloaded owner-only full diagnostic archives may include raw text.
  Owner direction on 2026-06-02: stop this Reader ergonomics push after #266.
  Owner later approved only the #268 marked-fragment persistence slice.
  Deferred/unfinished ideas remain cross-page completion, block notes/comments,
  review report export, stronger chapter/page outline and visual intra-block
  diff. Publisher/editor workspaces are future TBD scope and are not planned
  for immediate implementation.
  These slices remain owner-only and do not claim physical page fidelity.
  Design reference:
  `docs/superpowers/specs/2026-06-01-internal-before-after-reader-design.md`.
  Issue split:
  [#181](https://github.com/ogirkoviylord/folioloom_main/issues/181) for the
  TXT local HTML report,
  [#182](https://github.com/ogirkoviylord/folioloom_main/issues/182) for the
  generic DOCX/EPUB block model,
  [#183](https://github.com/ogirkoviylord/folioloom_main/issues/183) for the
  DOCX renderer spike and
  [#184](https://github.com/ogirkoviylord/folioloom_main/issues/184) for the
  EPUB renderer spike,
  [#189](https://github.com/ogirkoviylord/folioloom_main/issues/189) for the
  EPUB explicit-input local HTML report,
  [#191](https://github.com/ogirkoviylord/folioloom_main/issues/191) for the
  sandboxed EPUB XHTML chapter preview inside the local report,
  [#193](https://github.com/ogirkoviylord/folioloom_main/issues/193) for
  local CSS and safe raster image inlining inside the preview panes,
  [#195](https://github.com/ogirkoviylord/folioloom_main/issues/195) for the
  explicit-input DOCX structure preview report,
  [#197](https://github.com/ogirkoviylord/folioloom_main/issues/197) for CLI
  format auto-detection by `.txt`, `.docx` and `.epub` extension, and
  [#199](https://github.com/ogirkoviylord/folioloom_main/issues/199) for a
  narrow owner-only internal admin UI over the existing renderer.
  DOCX recommendation: keep semantic/block preview as the default for now, use
  the #195 explicit-input structure preview and block report, use local
  LibreOffice only as reference/QA on approved fixtures, and require a separate
  owner-approved prototype/implementation issue before adding `docx-preview`,
  Mammoth or LibreOffice automation as a dependency/runtime path.
  EPUB recommendation: keep semantic/block preview as the default for now,
  use the #189/#191/#193 explicit-input local report, sandboxed XHTML preview
  and limited resource inlining before adding a book-like reader dependency,
  and keep EPUBCheck as validation/reference only.
  Suggested acceptance criteria: local tool generates a side-by-side
  source/translation report from existing adapter blocks for explicit
  synthetic/test/public-domain/permissive or owner-approved TXT/DOCX/EPUB
  files, can auto-detect those three formats by extension in the CLI/UI, keeps
  any UI owner-only/internal, does not read live runtime `var/`, does not add
  public routes, does not add production dependencies without approval,
  HTML-escapes displayed text and metadata, and does not claim DOCX full visual
  fidelity or release readiness.

- Task: Add metadata-only Alerts/Backups owner report.
  Phase: 2
  Priority: Medium
  Risk: Medium
  Agent suitability: safe if metadata-only; needs architect for new admin UI
  Suggested acceptance criteria: owner can see provider, queue/worker, disk,
  failed-job and backup/restore status without raw text/secrets, stack traces,
  backup archives or restored files. Admin UI expansion is later.

- Task: Decide CI policy.
  Phase: 3
  Priority: Medium
  Risk: Medium
  Agent suitability: done / monitor
  Status: Done 2026-05-17.
  Suggested acceptance criteria: GitHub Actions Python checks are advisory for
  now, local gates remain required, and docs keep run/pass status Unknown until
  PR/check evidence exists.

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
