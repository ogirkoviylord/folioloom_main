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

### 2026-05-16 - Release decisions: complete Gate B before free closed beta

Status: Active

Decision:
- Free closed beta must wait until every Gate B item has recorded evidence.
- No implicit Gate B deferrals are approved.
- Any future exception requires a new explicit owner decision naming the affected
  Gate B item and accepted risk.

Evidence:
- Owner selected "complete Gate B first" during GitHub issue #71 implementation
  on 2026-05-16.
- `docs/restart/release-gates.md`: Gate B still contains unchecked blockers.
- `docs/restart/gate-b-evidence-report.md`: issue #71 owner decision register.

Reason:
- The repository evidence shows a working closed-beta foundation, but not full
  free closed beta readiness. Preview evidence does not prove upload/TTL,
  real-file, restart, backup/restore, server smoke or other Gate B items.

Consequences:
- Agents must not claim free closed beta readiness until Gate B evidence is
  recorded for every item.
- Unchecked Gate B items remain release blockers.
- Later deferrals are not assumed; they require another explicit owner approval.

Human approval required to change:
- yes; this changes release threshold and accepted release risk.

### 2026-05-17 - Release decisions: free beta success metrics

Status: Active

Decision:
- Free beta success metrics are split into hard launch guardrails and
  translation-quality learning metrics.
- Hard launch guardrails:
  - Gate B must be complete before free beta.
  - Recovery reliability: `0` lost accepted jobs in Gate B
    cancel/resume/bot-restart/worker-restart checks.
  - Safety/privacy: `0` known raw document text, prompt, translation or API key
    leaks in logs, admin views, telemetry or artifacts.
  - Cost/control: `0` cap or kill-switch breaches.
- Translation-quality learning metrics:
  - For every completed beta document, collect per-target-language human
    feedback: `usable`, `not usable` or `needs review`, plus short reason tags.
  - Existing automated Russian/Ukrainian quality metrics may be used as
    regression diagnostics where reference samples exist.
  - Automated Russian/Ukrainian scores are not a universal success metric for
    every target language.

Evidence:
- Owner approved this split during GitHub issue #71 implementation on
  2026-05-17.
- `src/translator_service/translation_metrics.py` provides reference-based
  `meteor_core` and `chrf` scoring.
- `src/translator_service/admin/quality.py` aggregates Russian and Ukrainian
  reference sample scores.
- `src/translator_service/admin/quality_runner.py` currently writes Russian
  regression candidate runs.
- `docs/superpowers/specs/translation-language-quality-methodology.md` defines
  per-language quality profile methodology.

Reason:
- Project readiness and translation quality are different questions.
- Current automated quality scoring is useful for languages with reference
  suites, but it does not cover every target language equally.
- Early free beta should keep reliability/privacy/cost guardrails strict while
  using real user/document feedback to learn where translation quality fails by
  language and document type.

Consequences:
- Agents must not claim a universal automated translation-quality score across
  all target languages.
- Russian/Ukrainian automated scores can support regression review, but free
  beta success also requires per-target-language human feedback.
- Learning metrics do not relax hard Gate B guardrails.

Human approval required to change:
- yes; this changes beta success criteria and release evidence expectations.

### 2026-05-17 - Release decisions: Gate B real-file corpus policy

Status: Active

Decision:
- Gate B real-file testing may use public-domain and clearly
  permissive-licensed documents from free libraries and other internet sources.
- Random internet documents are allowed only when the corpus manifest records a
  clear rights basis, source/license URL and why the file is authorized for
  testing.
- "Free to read online" alone is not a sufficient rights basis.
- Synthetic/generated fixtures may live in the repository when they contain no
  sensitive or questionable copyrighted text.
- Real source documents and translated outputs stay out of git by default.
- Release artifacts default to metadata-only reports: fixture id, source/license
  URL, format, size, language pair, command, pass/fail, safe error class and
  validation/openability notes.
- Raw source documents or translated outputs may be retained only in approved
  local/test artifacts and should be deleted after Gate B review unless the
  owner explicitly approves retention for that fixture.

Evidence:
- Owner approved free libraries and random documents as test material during
  GitHub issue #71 implementation on 2026-05-17, with the repository guardrail
  that authorized/public-domain/permissive-license basis must be recorded.
- `docs/restart/real-file-test-matrix.md` already requires authorized files and
  a manifest with source and rights basis.

Reason:
- Gate B needs real TXT/DOCX/EPUB files that resemble user documents, not only
  synthetic unit fixtures.
- The project must not weaken rights, privacy or raw-text guardrails by treating
  any free-to-read document as safe to store or translate as a release artifact.

Consequences:
- Agents may build a real-file corpus from Project Gutenberg-like public-domain
  sources and other clearly permissive sources.
- Agents must record rights basis per fixture.
- Agents must not commit raw copyrighted/private source documents or translated
  outputs without explicit per-fixture approval.

Human approval required to change:
- yes; this affects legal/privacy guardrails and release evidence handling.

### 2026-05-17 - Release decisions: retention/delete verification scope

Status: Active

Decision:
- TTL/delete verification may run on synthetic test data by default.
- A second verification pass may run only on an owner-approved disposable copy of
  beta/runtime data.
- Agents must not run TTL cleanup/delete checks on live beta/server data.
- Passing evidence requires idempotent lifecycle checks for source, final,
  partial and quarantine objects; safe metadata-only logs/admin output; no raw
  text exposure; and no impact on live runtime data.

Evidence:
- Owner approved this recommendation during GitHub issue #71 implementation on
  2026-05-17.
- `docs/restart/upload-safety-and-retention.md` defines proposed TTL defaults
  and requires idempotent TTL jobs.
- `docs/restart/release-gates.md` marks TTL cleanup as an unchecked Gate B item.

Reason:
- Delete/TTL verification is destructive-adjacent user-data work.
- Synthetic data and disposable copies allow agents to gather evidence without
  risking real user documents, runtime databases, object storage or backups.

Consequences:
- Agents may design and run retention/delete tests against synthetic fixtures
  without additional approval when no live/runtime data is touched.
- Any disposable-copy verification must name the approved copy/environment and
  must not operate on live beta/server data.
- Live data deletion, runtime `var/` cleanup, backup mutation or destructive
  server operations remain forbidden without separate explicit approval.

Human approval required to change:
- yes; this affects user-data handling, destructive-adjacent verification and
  release evidence.

### 2026-05-17 - Release decisions: Gate B backup/restore evidence policy

Status: Active

Decision:
- Backup exists to restore accepted beta work after server/runtime failure:
  jobs/work units, user-visible history, source/intermediate/partial/final
  files, admin/beta settings and privacy-safe operational metadata.
- Gate B backup/restore evidence may be collected on an owner-approved
  disposable local compose environment, disposable VPS/test server, disposable
  copy of beta runtime data or owner-approved beta environment.
- Running backup/restore checks on live beta/server data requires explicit owner
  approval for that exact run.
- Passing evidence requires:
  - backup manifest verification passes with `scripts/verify_backup_export.py`;
  - restore rehearsal follows `docs/deployment/restore-runbook.md`;
  - restored jobs/work units, user-visible history, files and admin/beta
    settings are usable enough for beta recovery;
  - no raw document text, prompts, translations, API keys, real `.env*` files or
    secrets appear in evidence;
  - admin remains SSH-tunnel-only.
- Release artifacts must be metadata-only reports. Do not commit backup
  archives, restored files, real env files, secrets or translated outputs.

Evidence:
- Owner approved this policy during GitHub issue #71 implementation on
  2026-05-17.
- `README.md` documents backup export and manifest verification commands.
- `docs/deployment/restore-runbook.md` documents restore rehearsal and already
  says to use a test server or disposable copy first.
- `docs/restart/release-gates.md` marks backup verify and restore rehearsal as
  unchecked Gate B items.

Reason:
- Backup scripts alone do not prove recoverability.
- Backup archives may contain user documents and operational state, so they are
  sensitive artifacts rather than public PR evidence.

Consequences:
- Agents may collect metadata-only backup/restore evidence in approved
  disposable or explicitly approved beta environments.
- Agents must not mutate live beta/server backup or restore state without
  exact-run owner approval.
- Existing backups do not imply user erasure from backups unless a separate
  backup retention/deletion policy says so.

Human approval required to change:
- yes; this affects user data, backups/restore, deployment-adjacent operations
  and release evidence.

### 2026-05-17 - Release decisions: Gate B DOCX visual QA threshold

Status: Active

Decision:
- Gate B DOCX openability/visual QA uses local LibreOffice Writer as the
  approved reader/tool.
- A DOCX fixture passes the visual QA threshold only when it opens without a
  repair/recovery prompt and has no blocker visual issues.
- Blocker visual issues include unreadable or missing translated content,
  broken document structure that makes the file unusable, corrupted tables or
  lists that materially harm readability, visible placeholders/debug strings,
  provider tracebacks, raw errors or other unsafe text.
- Pixel-perfect matching with the source document is not required for free
  closed beta.
- Minor and major visual issues may be recorded as notes, but only blocker
  issues block the fixture by default.

Evidence:
- Owner selected the recommended local LibreOffice Writer threshold during
  GitHub issue #71 implementation on 2026-05-17.
- `docs/restart/real-file-test-matrix.md` requires DOCX openability/visual QA
  notes.
- `docs/restart/release-gates.md` marks DOCX openability/visual QA as a Gate B
  evidence item.

Reason:
- DOCX can be technically produced but still unusable for readers if opening,
  structure, tables, lists or visible debug/error text fail.
- Local LibreOffice Writer gives agents a reproducible offline reader without
  sending documents to online services.
- Free closed beta needs practical usability evidence, not pixel-perfect layout
  parity.

Consequences:
- Agents may collect DOCX Gate B visual QA evidence using local LibreOffice
  Writer and metadata-only notes.
- DOCX Gate B remains blocked until approved fixtures are actually checked and
  results are recorded.
- Using Microsoft Word as an additional reviewer spot-check is allowed later but
  is not required by this decision.

Human approval required to change:
- yes; this changes Gate B pass/fail criteria for DOCX release evidence.

### 2026-05-17 - Release decisions: Gate B Alerts/Backups visibility approach

Status: Active

Decision:
- For Gate B free closed beta evidence, Alerts MVP and Backups visibility may be
  satisfied by a metadata-only owner runbook/report instead of new admin UI.
- The owner report must summarize provider, queue/worker, disk/storage,
  failed-job and backup/restore status without raw document text, prompts,
  translations, API keys, stack traces, backup archives or restored files.
- Admin UI expansion for these signals is deferred to a later follow-up task.
- Future admin UI should be additive and should not require redesigning the
  whole admin console whenever bot functionality changes.

Evidence:
- Owner selected the owner runbook/report option during GitHub issue #71
  implementation on 2026-05-17.
- Owner noted that prior admin-system work created maintenance pressure because
  new bot features often required admin rewrites.
- `docs/restart/release-gates.md` allows admin visibility or documented owner
  report evidence for Gate B.
- `docs/ROADMAP.md` lists Alerts MVP and Backups visibility as operational
  visibility gaps.

Reason:
- A metadata-only owner report is smaller, lower-risk and faster for free
  closed beta than expanding the admin console now.
- It avoids increasing admin routes/RBAC/security surface before Gate B evidence
  is collected.
- The owner still needs operational visibility before beta, but not necessarily
  a full UI for the first free closed beta.

Consequences:
- Agents should implement/collect Gate B Alerts/Backups visibility evidence as
  an owner runbook/report first.
- Gate B remains blocked until the report exists and covers the required
  signals.
- Admin UI for alerts/backups remains a later roadmap item, not a Gate B
  requirement unless the owner changes this decision.

Human approval required to change:
- yes; this changes operational visibility scope and release evidence
  expectations.

### 2026-05-17 - Release decisions: Gate B EPUB validation approach

Status: Active

Decision:
- Gate B EPUB validation uses local/offline EPUBCheck as the required validation
  tool.
- Online EPUB validation services are not approved.
- EPUBCheck is a release verification tool, not a production dependency.
- EPUBCheck errors block the fixture by default.
- EPUBCheck warnings must be recorded and triaged, but do not automatically
  block the fixture unless the warning indicates a beta-relevant usability,
  safety or compatibility risk.
- If EPUBCheck is unavailable in the approved verification environment, EPUB
  validation remains `Blocked` or `Unknown`; agents must not mark it `Pass`.
- EPUB validation remains blocked until approved EPUB fixtures pass EPUBCheck or
  failures receive explicit owner triage.

Evidence:
- Owner selected the recommended local EPUBCheck option during GitHub issue #71
  implementation on 2026-05-17.
- Local exploratory tool check on 2026-05-17 ran EPUBCheck v5.3.0 using a local
  Temurin JRE and confirmed the tool starts locally.
- The same exploratory run found validation errors in selected existing EPUB
  fixtures, so current EPUB evidence is blocked rather than passing.

Reason:
- EPUB files can open in some readers while still being structurally invalid or
  brittle across readers.
- EPUBCheck is the clearest local/offline standard for EPUB release validation.
- Keeping EPUBCheck outside production dependencies avoids expanding runtime
  deploy scope.

Consequences:
- Gate B EPUB evidence must include local EPUBCheck command/output summaries for
  approved EPUB fixtures.
- Agents must not upload EPUB source/output files to online validators.
- Current failing EPUB fixtures require fixes or explicit owner triage before
  EPUB Gate B can pass.

Human approval required to change:
- yes; this changes Gate B pass/fail criteria and tool policy for EPUB release
  evidence.

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
- yes; deployment/infrastructure относятся к high-risk зонам по `AGENTS.md`.

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

### 2026-05-14 - Reliability decisions: issue #31 unsafe model-output classification

Status: Active

Decision:
- DeepSeek/model-output safety failures such as `tool_or_execution_claim` are
  classified as `unsafe_model_output`, separate from API key/provider
  infrastructure failures.
- Unsafe model-output failures remain blocked.
- A single unsafe model-output failure must not mark the selected provider
  channel as `degraded`, reduce the adaptive provider limit or open the
  provider circuit.
- Admin/runtime diagnostics use the metadata label `unsafe_model_output`.
- Worker/scheduler retry semantics are unchanged by this decision.

Evidence:
- GitHub issue [#31](https://github.com/ogirkoviylord/folioloom_main/issues/31)
  documents the owner-reported provider-health symptom and desired follow-up.
- Owner approved the classification, throttle/health semantics and admin label
  on 2026-05-14.
- Code behavior is covered by focused provider, admin runtime/live and
  provider-health tests.

Reason:
- The reported failure was unsafe model output for a document/work unit, not
  evidence that an API key, quota, auth, billing, timeout or rate-limit path was
  broken. Operator diagnostics should remain actionable without weakening
  model-output safety.

Consequences:
- Admin can distinguish model-output safety blocks from key/provider
  infrastructure failures.
- Real provider outages still need to reduce capacity or degrade health through
  their existing auth, billing, 429, timeout, unavailable or malformed-response
  paths.
- Repeated unsafe outputs and any chunking/repair/retry strategy changes remain
  out of scope until separately approved.

Human approval required to change:
- yes; this affects external provider behavior, admin diagnostics and safety
  classification.

### 2026-05-10 - Testing approach: local gates first, minimal CI workflow present

Status: Active

Decision:
- Основные verification commands: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall src`, `scripts/predeploy_check.sh`.
- `scripts/predeploy_check.sh` является текущим predeploy gate.
- Repo-wide ruff cleanup не является free closed-beta release blocker.
- `.github/workflows/checks.yml` exists as a minimal GitHub Actions workflow for compile and unit tests on PRs and pushes to `main`.
- GitHub Actions Python checks are advisory for now, not the sole source of truth.
- Local gates remain required for PR-ready work: focused tests for touched areas, plus full unittest/compileall/predeploy when scope is broad or release-adjacent.
- Agents must not claim CI passed unless visible PR/check evidence was inspected.
- If CI is not inspected, report CI status as `Unknown`.
- Expanding CI or making it required is a later owner-approved task.

Evidence:
- `README.md`: Verification Commands.
- `docs/restart/release-gates.md`: Common Verification Commands.
- `CURRENT_PROJECT_STATE.md`: Последняя зафиксированная проверка.
- `pyproject.toml`: dev dependencies and ruff config.
- `.github/workflows/checks.yml`: Python 3.13 compile and unit test workflow.
- Owner approved the advisory-CI/local-gates policy during GitHub issue #71
  implementation on 2026-05-17.

Reason:
- Репозиторий фиксирует local verification gates and now contains a minimal
  GitHub Actions workflow.
- Several Gate B checks are not covered by CI: server smoke, backup/restore,
  real-file matrix, EPUB validation, DOCX visual QA and manual owner decisions.

Consequences:
- AI-агентам нельзя утверждать, что CI passed, без видимого PR/check evidence.
- Для code changes нужно запускать focused tests и релевантные local gates; для docs-only changes можно не запускать test suite, если это явно указано в отчете.
- Passing GitHub Actions does not imply release readiness or Gate B completion.

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
- После задач отчитываться по формату из `AGENTS.md`.

Evidence:
- `AGENTS.md`.

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
- `AGENTS.md`.
- `docs/CONTEXT_MAP.md`.

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

### 2026-05-22 - Risk / safety decisions: local malware scanning is planned

Status: Active

Decision:
- FolioLoom should add a local malware/AV scanning gate for uploaded
  TXT/DOCX/EPUB files as part of upload hardening.
- Uploaded files should enter quarantine before parsing or translation.
- The default direction is local scanning, such as a ClamAV daemon/sidecar,
  before parser/container checks.
- Public VirusTotal-style file submission must not be used as the default path
  for user documents because uploaded books/manuscripts can be rights-sensitive
  and private.
- Scanner verdicts and metadata may be stored for owner/admin diagnostics, but
  raw document text, extracted snippets, prompts, translations and secrets must
  remain out of logs/admin/release artifacts.

Evidence:
- Owner decision in planning conversation on 2026-05-22: "мы эту темку сто
  процентов добавим".
- `docs/restart/upload-safety-and-retention.md`: Malware Scanning Baseline.
- `docs/restart/release-gates.md`: Gate B now includes a local malware/AV
  scanning gate or explicit owner deferral.
- GitHub issues [#91](https://github.com/ogirkoviylord/folioloom_main/issues/91)
  through [#95](https://github.com/ogirkoviylord/folioloom_main/issues/95)
  split the design, scanner contract, ClamAV adapter, upload-flow wiring and
  release evidence work.

Reason:
- User uploads are untrusted input and may include private or rights-sensitive
  documents.
- Local scanning reduces third-party disclosure risk compared with automatic
  public multi-engine scanning.
- Scanning complements, but does not replace, extension allowlists, magic bytes,
  ZIP/container inspection, parser sandboxing, size limits and redaction.

Consequences:
- Implementation must be split into small issues and reviewed by Architect
  before code changes.
- Any ClamAV sidecar, Docker/deployment change, new production dependency,
  scanner socket/service configuration, retention behavior or runtime data
  handling requires explicit owner approval in the relevant issue.
- Agents must not claim malware scanning is implemented until code, tests and
  Gate B evidence exist.

Human approval required to change:
- yes; this touches security, privacy, user data, deployment and dependency
  boundaries.

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
- `AGENTS.md`.
- `docs/PROJECT_BRIEF.md`: AI-agent usage.

Reason:
- Repository rules and project brief both name role expectations.

Consequences:
- Large tasks should be split, risk-reviewed, implemented in small diffs, reviewed, and documented.
- AI-агентам нельзя skip review/scribe expectations for broad or risky work.

Human approval required to change:
- no for clarifying role usage; yes for changing repository workflow.

### 2026-05-23 - Process decisions: Skill Dispatch Contract v1

Status: Active

Decision:
- Every AI agent must apply the `AGENTS.md` Skill Dispatch Contract before
  using a skill, changing files, running operations or declaring work complete.
- The contract records task classification, risk level, primary role/skill,
  supporting skills, required docs, approval status, allowed action and
  verification plan.
- If a task matches multiple categories, the highest-risk route wins.
- If any matched route requires human approval and approval evidence is missing,
  the agent stops at analysis and uses `TBD`.
- Repo-level `.agents/skills/*` skills win over global skills with similar
  names inside this repository.
- Specialized skills can provide domain context but cannot override
  `AGENTS.md`, `docs/QUALITY_GATES.md`, `docs/RISK_REGISTER.md`, task scope or
  approval gates.

Evidence:
- Owner approval in the 2026-05-23 planning thread to implement the approved
  skill dispatch system.
- `AGENTS.md`: Skill Dispatch Contract.
- `docs/AGENT_SKILL_ROUTING.md`: detailed routing reference.
- `.agents/skills/*/SKILL.md`: repo-level skill preambles now defer to the
  dispatcher and stricter safety gates.

Reason:
- The repository already assumes Orchestrator, Architect, Implementer, Reviewer
  and Scribe roles, but previous skill routing was spread across several
  documents and could be applied inconsistently.
- A compact dispatcher reduces accidental scope expansion, wrong skill
  selection, missing approval checks and overstated verification.

Consequences:
- Future agents must include a routing receipt in task reports after changes.
- Implementer Agent must not start unless the task has a clear issue or
  explicit scoped task, acceptance criteria, verification plan, risk
  classification, approval status, likely touched areas and out-of-scope list.
- Reviewer Agent should check whether the selected route matched the task risk
  and approval gates.
- Changes to this workflow should update `AGENTS.md`,
  `docs/AGENT_SKILL_ROUTING.md`, relevant repo-level skills and this decision.

Human approval required to change:
- yes for changing repository workflow; no for narrow clarifications that do
  not weaken routing, approval or safety gates.

### 2026-05-23 - Process decisions: Skill Domain Catalog v2

Status: Active

Decision:
- `docs/AGENT_SKILL_ROUTING.md` includes a Skill Domain Catalog for choosing
  supporting global/plugin skills after the primary repo-level route is chosen.
- Agents should use exactly one primary repo-level skill and normally 0-2
  supporting skills.
- More than 2 supporting skills are reserved for explicit planning, research,
  review or architecture tasks where broad domain coverage is the deliverable.
- Supporting skills are helpers only: they cannot become workflow owners,
  expand scope, override repo-level skills, or bypass approval gates.

Evidence:
- Owner approval in the 2026-05-23 planning thread to add a catalog layer for
  the broader installed skill set.
- `docs/AGENT_SKILL_ROUTING.md`: Supporting Skill Selection Rules, Skill
  Domain Catalog and Trigger Examples.

Reason:
- The repository has many installed skills across product, engineering,
  security, frontend, docs, cloud, payment and AI domains.
- Without a catalog, agents may either ignore useful skills or overuse unrelated
  skills, increasing token use and scope risk.

Consequences:
- Agents should first choose the repo-level route, then select only directly
  relevant supporting skills from the domain catalog.
- Reviewer should check that supporting skills did not expand scope or bypass
  project gates.
- Scribe should keep the catalog aligned with available skills and active
  project guardrails.

Human approval required to change:
- no for catalog maintenance that keeps or tightens existing gates; yes for
  changes that weaken routing, approval, payment, security, privacy, deployment,
  user-data or product-scope guardrails.

### 2026-05-23 - Process decisions: owner-facing responses are Russian by default

Status: Active

Decision:
- AI agents should respond to the owner in Russian by default unless the owner
  explicitly asks for another language.
- Code identifiers, commands, file paths, tool names and quoted source text
  should stay in their original language.

Evidence:
- Owner instruction in the current thread on 2026-05-23: add that answers for
  the owner should be in Russian.
- `AGENTS.md`: Core rules.
- `docs/AGENT_SKILL_ROUTING.md`: Skill Dispatch Contract.

Reason:
- Russian is the owner's working language in this repository conversation.

Consequences:
- Intermediate updates, final task reports and owner-facing agent discussion
  should be Russian by default.
- Repository docs can keep source terms, command names, file paths and existing
  English workflow labels where that preserves clarity.

Human approval required to change:
- yes; this is an owner-facing workflow preference.

## Decisions that still need human approval

- Decision recorded: free closed beta waits for complete Gate B evidence.
  Current status: Active decision recorded on 2026-05-16.
  Consequence: unchecked Gate B items block beta; no implicit deferrals are approved.
  Human approval required to change: yes.

- Decision recorded: free beta success metrics.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: hard guardrails block beta; translation-quality feedback is
  collected per target language, while Russian/Ukrainian automated quality
  scores remain regression diagnostics rather than universal launch metrics.
  Human approval required to change: yes.

- Decision recorded: approved real-file TXT/DOCX/EPUB corpus and artifact retention policy.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: public-domain/permissive-license free-library and internet
  documents may be used when the rights basis is recorded; raw source documents
  and translated outputs stay out of git by default.
  Human approval required to change: yes.

- Decision recorded: retention/delete verification scope.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: agents may run TTL/delete verification on synthetic data by
  default, may run a second pass only on an owner-approved disposable
  beta/runtime copy, and must not run cleanup/delete checks on live beta/server
  data.
  Human approval required to change: yes.

- Decision recorded: Gate B backup/restore evidence policy.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: backup/restore evidence may be collected only in owner-approved
  disposable/local/test/copy environments or an explicitly approved beta
  environment; live beta/server data requires exact-run owner approval; release
  artifacts are metadata-only.
  Human approval required to change: yes.

- Decision recorded: CI policy.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: GitHub Actions Python checks are advisory for now; local gates
  remain required for PR-ready work; agents must report CI status as `Unknown`
  unless visible PR/check evidence was inspected.
  Human approval required to change: yes.

- Decision recorded: EPUB validation approach for Gate B.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: Gate B EPUB validation requires local/offline EPUBCheck. Online
  EPUB validation services are not approved. EPUBCheck is a release verification
  tool, not a production dependency. Errors block fixtures; warnings are
  recorded and triaged.
  Human approval required to change: yes.

- Decision recorded: DOCX visual/openability QA threshold.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: Gate B DOCX QA uses local LibreOffice Writer; pass means the
  fixture opens without repair/recovery prompt and has no blocker visual issues.
  Pixel-perfect source parity is not required for free closed beta.
  Human approval required to change: yes.

- Decision recorded: Alerts/Backups visibility approach for free beta.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: Gate B may use a metadata-only owner runbook/report for provider,
  queue/worker, disk/storage, failed-job and backup/restore status. Admin UI
  expansion is deferred to a later follow-up task.
  Human approval required to change: yes.

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

- Decision needed: exact malware scanner implementation and failure policy.
  Why it matters: upload scanning affects security, privacy, user-data
  handling, deployment, dependencies and beta release gates.
  Suggested options: local ClamAV daemon/sidecar; pluggable scanner contract
  with fake/local implementation first; paid/private external scanning only
  after privacy/legal review.
  Recommended default: implement a scanner contract first, then local ClamAV
  with fail-closed beta behavior for timeout/unavailable/error verdicts.
  Risk if left undecided: agents may either skip scanning or send private user
  documents to an inappropriate external scanning service.

## Things agents must not reinterpret

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
- Не отправлять user documents в public malware scanning services по умолчанию.
- Не считать malware/AV scanning implemented без focused issue, tests and Gate
  B evidence.
- Не переписывать архитектуру без отдельного approved plan.
- Не трактовать historical plans/specs as current roadmap без сверки с active source of truth.
- Не хранить и не показывать raw document text, prompts, translations или API keys в logs/admin/safety telemetry.
