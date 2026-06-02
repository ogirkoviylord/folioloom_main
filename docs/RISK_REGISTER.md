# Risk Register

## 1. Назначение

Этот документ нужен Architect Agent, Reviewer Agent и владельцу проекта, чтобы заранее видеть зоны, где изменение может сломать продукт, данные, безопасность, приватность, деньги, эксплуатацию или AI-agent workflow.

Риски из этого реестра нужно проверять до risky changes: перед изменениями в auth/security, user data, storage, jobs/scheduler, payments/pricing, deployment, secrets, legal/privacy, внешних интеграциях и release readiness. AI-агенты не должны снижать уровень риска самовольно. Если риск кажется ниже, нужен evidence из кода, тестов, docs и, для High/Critical зон, approval владельца.

Документ не является релизным go/no-go. Он помогает принять решение, какие проверки, owners и approvals нужны до изменения.

## 2. Risk levels

- Low - можно делать обычным Implementer Agent в маленьком focused diff с релевантной проверкой.
- Medium - нужен Reviewer Agent, который проверит scope, tests, docs и unintended behavior changes.
- High - нужен Architect Agent и human approval до изменения, потому что зона влияет на данные, безопасность, эксплуатацию, деньги, релиз или базовую архитектуру.
- Critical - нельзя менять без отдельного плана, explicit approve владельца и rollback/recovery path. Для destructive/runtime/deployment действий нужен свежий backup или доказательство, почему он не требуется.

## 3. Risk table

| ID | Risk | Area | Level | Evidence | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|---|
| R-001 | Potential: целевая аудитория будущих paid users не зафиксирована | Product | Medium | `docs/PROJECT_BRIEF.md` помечает будущих платных пользователей как TBD | Агенты могут строить не тот paid/public продукт | Держать paid/public вне scope до решения; фиксировать ICP перед Gate C/D | Human / Orchestrator | Needs decision |
| R-002 | Scope creep за пределы TXT/DOCX/EPUB, Telegram-first и closed beta | Product | High | `README.md`, `README.project.md`, `docs/DECISIONS.md`, `docs/PROJECT_BRIEF.md` запрещают PDF/OCR/MOBI/FB2/public SaaS сейчас; GitHub issue [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23) is FB2 idea only | Раздувание QA, security, support и parser surface | Любое расширение форматов/каналов только через Architect plan, fixture rights basis, dependency review, verification plan and human approval | Human / Architect | Open |
| R-003 | Unclear MVP readiness: foundation есть, но Gate B не закрыт | Product | High | `docs/restart/release-gates.md` содержит unchecked Gate B items; `CURRENT_PROJECT_STATE.md` перечисляет gaps; issue #56 verifies only the free-preview slice | Beta может быть открыта без upload safety, TTL, real-file QA, restore evidence or other Gate B checks | Перед beta нужен Gate B evidence report или signed deferrals | Reviewer / Human | Open |
| R-004 | Formal success criteria для beta могли быть неясными | Product | Medium | `docs/DECISIONS.md` and `docs/PROJECT_BRIEF.md` record owner-approved free beta success metrics from 2026-05-17 | Метрики могут быть забыты или смешаны с language-specific translation-quality scores | Keep hard guardrails separate from translation-quality learning metrics; Reviewer checks release evidence against the approved metrics | Human / Scribe | Mitigated / watch |
| R-005 | Core workflow instability в cancel/resume/restart/worker recovery | Technical | High | Gate B unchecked: cancel/resume/restart, worker restart, bot restart; код содержит persistent jobs/work units and worker loop; issue #30 child PRs #36-#39 added focused cancel/provider/admin regression coverage | Accepted jobs могут стать невидимыми, stuck или потерять partial/final state | Targeted restart/cancel/resume tests, server smoke evidence, release report; keep issue #30 safeguards intact | Architect / Reviewer | Open |
| R-006 | Incomplete release verification evidence | Technical | Medium | issue #56 recorded local focused preview tests, full unittest, compileall and predeploy passing on 2026-05-16; real-file/server-smoke/restore/restart evidence remains incomplete | Preview evidence can be mistaken for full beta readiness if remaining release checks are skipped | Перед code/release changes запускать focused tests; перед release - full suite, compileall, predeploy, server smoke and release-specific evidence where applicable | Reviewer | Open |
| R-007 | CI policy can be overstated | Technical | Medium | `.github/workflows/checks.yml` exists; issue #71 records GitHub Actions Python checks as advisory and local gates as required | Regression prevention can be overstated if agents claim CI without visible check evidence or treat advisory CI as release readiness | Agents must report CI as Unknown unless visible PR/check evidence was inspected; Reviewer still requires local verification evidence | Human / Reviewer | Mitigated / watch |
| R-008 | Brittle parsing/processing for DOCX/EPUB/TXT real files | Technical | High | `docs/restart/real-file-test-matrix.md`; Gate B unchecked: EPUB validation and DOCX openability/visual QA; issue #71 approved local/offline EPUBCheck for EPUB and local LibreOffice Writer threshold for DOCX visual QA | Unit tests могут пройти, а реальные файлы не открываются или теряют структуру | Execute authorized real-file matrix; add negative fixtures; record release report; for EPUB use local/offline EPUBCheck; for DOCX use local LibreOffice Writer and require opens without repair plus no blocker visual issues | Reviewer / Implementer | Open |
| R-009 | Upload hardening/quarantine baseline can regress or be overclaimed beyond local synthetic evidence | Security / Technical | High | `docs/restart/upload-safety-and-retention.md`; issue #73 local verification on 2026-05-28 checks TXT/DOCX/EPUB-only upload validation, content/container validation before accepted source creation and negative synthetic fixtures for wrong extension/content mismatch, invalid/binary TXT, corrupt ZIP, traversal/absolute paths, archive size/count/compression limits, missing expected structure and executable-looking embedded paths | Unsafe containers could reach parser/worker paths if regression removes quarantine-first, container validation or worker accepted-source checks; agents may mistake this item for TTL/quarantine cleanup, real-file QA or full Gate B readiness | Keep negative fixture tests and reviewer pass; keep TTL/quarantine cleanup, real-file matrix and beta-server smoke as separate blockers | Architect / Reviewer | Mitigated / watch |
| R-010 | TTL cleanup/delete verification не подтверждены | Privacy / User data | High | Gate B unchecked; retention policy is proposed in `docs/restart/upload-safety-and-retention.md`; `LocalObjectStorage.delete()` exists; issue #71 approved synthetic/disposable-copy verification scope | Source/final/partial/quarantine data may remain longer than intended | Implement idempotent cleanup verification on synthetic data by default; use only owner-approved disposable beta/runtime copy for second pass; never live beta/server data | Human / Architect | Open |
| R-011 | Background jobs and scheduler concurrency/race conditions | Technical | High | `worker.py`, `scheduler.py`, `postgres_scheduler.py`; docs mention leases, capacity, fairness, provider caps | Duplicate claims, stuck leases, over-capacity provider calls, inconsistent usage accounting | Changes require targeted scheduler/worker/Postgres tests and Architect review | Architect / Reviewer | Open |
| R-012 | Storage/runtime data under `var/` and local object storage are high-risk | User data / Operational | High | `docker-compose.yml` mounts `./var`; `file_storage.py`; `docs/CONTEXT_MAP.md` marks `var/` as user/runtime data | Accidental edits/deletes can affect uploaded docs, results, DBs, logs | Do not edit runtime data without approval; backup before destructive operations | Human / Reviewer | Open |
| R-013 | Database/schema changes have no migrations directory | Database | High | `postgres_scheduler.py` contains schema SQL; no `migrations/`, `database/`, `db/` directories found | Manual schema drift or incompatible runtime state | Any schema/state change needs plan, tests, backup/restore impact review | Architect / Human | Unknown |
| R-014 | Error handling can leak unsafe details if new paths bypass redaction | Security / Privacy | High | `security_telemetry.py` safe payload allowlist; `admin/translation_logs.py` redacts sensitive keys; issue #78 synthetic local evidence fixed translation run artifact/archive redaction and created bug #117 for the found archive leak risk; docs allow raw source/translated text and raw prompt bodies only in approved owner-only diagnostic surfaces | Raw document text, prompts, translations, secrets or tracebacks could appear in new logs/admin/user-message paths if future changes bypass redaction | Reviewer checks redaction tests and admin/log/archive outputs for touched path; raw source/translated text and raw prompt bodies must stay confined to owner-only diagnostic surfaces | Reviewer / Implementer | Mitigated / watch |
| R-015 | Observability gaps: Alerts MVP and Backups visibility incomplete | Operational | Medium | `CURRENT_PROJECT_STATE.md`, `DOCUMENT_INDEX.md`, Gate B unchecked; issue #71 approved metadata-only owner runbook/report for Gate B with admin UI later | Owner may miss provider, queue, worker, disk, backup or restore problems | Add metadata-only owner runbook/report covering provider, queue/worker, disk/storage, failed jobs and backup/restore; defer admin UI expansion | Implementer / Reviewer | Open |
| R-016 | Admin auth/security is sensitive and tunnel-only | Security / Auth | High | `admin/auth.py`, `admin/rbac.py`, `docker-compose.yml` binds `127.0.0.1:62062`, docs say SSH tunnel only | Public exposure or auth weakening can compromise admin/runtime data | No bind/auth/RBAC changes without approval; keep SSH tunnel model until Gate D | Human / Architect | Open |
| R-017 | Permissions/RBAC model may be foundation-only | Security | Medium | `admin/rbac.py`, `admin/auth.py`, docs call owner/admin console closed-beta and SSH-only | Future named admins or public exposure could need stronger access policy | Treat public/named-admin changes as High; require security review | Architect / Human | Unknown |
| R-018 | Secrets and env files exist locally | Security / Secrets | Critical | Root contains real `.env`, `.env.dev`, `.env.beta`; `.env.server.example` placeholders; `admin/secrets.py` encrypts admin secrets | Reading, logging or editing secrets can expose Telegram, DeepSeek, admin or Postgres credentials | Do not read/modify real `.env*`; use examples only; rotate if exposure suspected | Human | Open |
| R-019 | External integrations can fail or create cost/auth/billing incidents | External integrations | High | `deepseek_client.py`, `deepseek_key_pool.py`, provider runtime/admin docs; telemetry includes auth/billing counters; issue #31 separates `unsafe_model_output` from key/provider failures | Translation failures, provider circuit open, cost spikes, key leakage, misleading provider health | Keep provider details internal; classify unsafe model output separately; review safe diagnostics; use caps/kill switch | Architect / Reviewer | Open |
| R-020 | User data includes uploaded documents and generated results | Privacy / User data | Critical | README describes source/intermediate/partial/final storage; `var/`; backup/restore docs | Privacy breach or loss of user files | User-data handling/retention/backups need approval, tests and rollback | Human / Architect | Open |
| R-021 | Legal/privacy/AUP/refund/support text is not production-ready | Privacy / Legal | High | Gate D unchecked: legal/privacy/AUP/refund docs; `docs/DECISIONS.md` says public production not ready | Agents may invent policy or public claims | Use TBD/Unknown; owner/counsel approval before public/legal copy | Human / Scribe | Needs decision |
| R-022 | Consent/rights confirmation must not be weakened | Legal / Product | High | README and `docs/DECISIONS.md` require authorized documents and rights confirmation | Legal risk if users translate unauthorized files without explicit confirmation | Bot/upload flow changes must preserve rights confirmation and tests | Reviewer / Architect | Open |
| R-023 | Data retention policy is proposed, not fully proven | Privacy / Operational | High | `docs/DECISIONS.md` marks upload safety/retention baseline Proposed; Gate B TTL unchecked | Misleading retention promises and user-data accumulation | Do not claim retention active until tests/evidence exist | Human / Reviewer | Open |
| R-024 | Payment/pricing launch is gated and incomplete | Payment / Business | Critical | `docs/restart/release-gates.md` Gate C unchecked; `billing.py` and `order_payments.py` are in-memory; pricing spec is draft | Money handling, refunds, reconciliation and support could be unsafe | No payment UI/paid jobs/pricing changes without Gate C plan and approval | Human / Architect | Open |
| R-025 | External provider costs can exceed beta budget if caps/keys changed casually | Business / Cost | High | README beta safety caps; `beta_safety.py`; provider/key/concurrency settings | Unexpected spend or provider throttling | Keep conservative caps; concurrency/key changes require review and owner approval | Human / Reviewer | Open |
| R-026 | Deployment and rollback are not routine agent actions | Deployment | Critical | `docker-compose.yml`, deploy scripts, VPS runbooks; AGENTS forbids production deployment without approval | Service downtime, data loss, public admin exposure | Deploy only with explicit approval, predeploy/server smoke, backup and rollback notes | Human / Architect | Open |
| R-027 | Backup/restore recoverability not fully evidenced for beta | Operational | High | Backup scripts/runbook exist; Gate B unchecked: backup verify, restore rehearsal, backups visibility; issue #71 approved metadata-only evidence policy and disposable/approved environment scope | Backups may exist but not restore usable jobs/files/admin state | Run backup verification and restore rehearsal before beta in owner-approved disposable/local/test/copy environment; live beta/server data requires exact-run owner approval | Human / Reviewer | Open |
| R-028 | Monitoring/incident/support workflow incomplete | Operational | High | Gate D unchecked: monitoring/alerts, incident runbooks, support workflow | Incidents may be noticed late or handled inconsistently | Define minimal incident/support process before public production | Human / Scribe | Needs decision |
| R-029 | AI agents changing too much or touching high-risk files | AI workflow | High | `AGENTS.md`, `docs/CONTEXT_MAP.md`, `docs/QUALITY_GATES.md` list guardrails | Broad diffs can weaken safety, auth, payments, deployment or user-data handling | Orchestrator splits tasks; Reviewer checks scope and high-risk files | Orchestrator / Reviewer | Open |
| R-030 | AI agents hallucinating docs or release readiness | AI workflow | Medium | AGENTS documentation rules require Unknown/TBD and confirmed facts | Docs may claim CI, production readiness, features or policies that do not exist | Scribe separates confirmed facts, assumptions, Unknown/TBD; Reviewer verifies evidence | Scribe / Reviewer | Open |
| R-031 | AI agents skipping tests or overstating verification | AI workflow | Medium | `docs/QUALITY_GATES.md`; CI status may be Unknown/not visible; local gates remain required evidence | Regressions can be merged or handoff can mislead owner | Final reports must list tests/checks run, visible CI evidence, or explain why none | Reviewer | Open |
| R-032 | Conflicting PRs/parallel agents in shared state machines | AI workflow | Medium | `docs/CONTEXT_MAP.md` lists conflict zones: scheduler/worker, bot/backend, provider/admin, auth/admin, deployment | Concurrent changes can create inconsistent contracts | Assign disjoint ownership; Architect coordinates cross-component work | Orchestrator / Architect | Open |
| R-033 | Admin/provider bulk diagnostics competing with active translation work | Admin / Provider / Cost | Medium | Issue #30 and PR #38 added a fail-closed guard for Admin -> AI Providers -> Test all active keys during active translations/provider requests | Uncontrolled diagnostics can add provider traffic during incidents or expose unsafe metadata if guardrails regress | Keep bulk key tests paused during active translations/provider requests; focused admin/provider tests and redaction review for future changes | Architect / Reviewer | Mitigated / watch |
| R-034 | Malware/AV scanning can regress or be misrepresented as broader Gate B readiness | Security / Privacy / User data / Deployment | High | Owner accepted local malware scanning on 2026-05-22; Gate B requires local malware/AV scanning or explicit owner deferral; issue #93 adds the app `clamd` adapter, issue #94 wires ledger-backed upload gating, issue #103 adds metadata-only admin visibility, issue #109 adds internal-only runtime shape and local runtime smoke, issue #95 records metadata-only Gate B malware/AV evidence on 2026-05-27, and issue #173 records a beta runtime mismatch where `clamd` was unhealthy/OOM-killed while bot scanner settings were not enforcing scanning. Metadata-only 173D smoke on 2026-06-01 found the running beta `clamd` still `unhealthy`, bot app settings still scanner-disabled, scanner env names absent and internal `clamd` unavailable. | Unsafe files may reach parsers/workers if the runtime gate is misconfigured or regresses, or private books/manuscripts may be submitted to inappropriate public scanning services; agents may mistake the malware/AV item pass for full upload safety or Gate B readiness | Keep local/internal scanning, quarantine-first flow, Upload Safety Ledger accepted-source gating, fail-closed beta errors and metadata-only logs/admin; production-like runtime defaults should require local `clamd` when scanner env is absent; keep public scanning services out of the default path; preserve #95 evidence scope and keep issue #73 upload-hardening scope, TTL/quarantine cleanup, real-file matrix, approved beta-server smoke and #173 target-host memory adequacy as separate evidence items | Human / Architect / Reviewer | Open |
| R-035 | Skill dispatch bypass or docs drift | AI workflow | Medium | `AGENTS.md` defines Skill Dispatch Contract; `docs/AGENT_SKILL_ROUTING.md` defines primary routing plus supporting skill domain catalog; `.agents/skills/*` must stay aligned | Agents may choose the wrong role/skill, skip approval evidence, overuse supporting skills, or read excessive docs if routing guidance drifts | Keep dispatcher compact in `AGENTS.md`, use 0-2 supporting skills by default, require routing receipts in final reports, and have Reviewer check route/approval consistency | Reviewer / Scribe | Open |
| R-036 | Beta Operations Console redesign can become a broad admin rewrite or add confusing/risky controls | Admin / Operational / AI workflow | Medium | Owner approved `docs/superpowers/specs/2026-05-31-beta-operations-console-redesign.md` as a before-beta design direction; admin auth/security, provider controls and user data remain high-risk zones | A broad redesign could delay Gate B work, hide existing diagnostic detail, weaken redaction, or put state-changing controls too close to read-only incident investigation | Split into small issues; start with Translation Failure Trace and safe evidence packet; keep advanced/raw views available; keep state-changing actions deeper and clearly classified; require Architect review for provider controls, auth/security, user data, database/state, deployment or dependency changes | Orchestrator / Architect / Reviewer | Open |
| R-037 | Owner-only raw text and prompt diagnostics can leak sensitive user/provider context if copied or exposed outside admin | Privacy / User data / Admin | High | Owner approved permanent raw translation text diagnostics on 2026-06-01 and raw prompt viewing in a dedicated owner-only diagnostic surface on 2026-06-02; normal details, safe archives, telemetry and APIs are intended to remain redacted/metadata-only | Screenshots, copied excerpts, support notes, PRs/issues, public admin exposure or broadened routes could leak source text, translated output or prompt bodies | Keep diagnostic routes SSH-tunneled and owner-only; do not include raw excerpts in docs/issues/PRs/support notes without exact owner approval; keep safe archives/telemetry/normal admin/API surfaces redacted; require review for new raw-text or raw-prompt surfaces | Human / Architect / Reviewer | Open |
| R-038 | Internal before-after reader can expand into raw-text admin/user access or overclaim format fidelity | QA / Privacy / Product | Medium | Owner approved `docs/superpowers/specs/2026-06-01-internal-before-after-reader-design.md` as an internal/dev design direction only; issue #199 approves a narrow owner-only internal admin UI; scope still excludes live `var/`, public routes, user-facing reader, publisher workspace, production dependencies and DOCX full-fidelity claims | A useful QA tool could drift into exposing source/translation text through admin/logs/artifacts, reading live user data, adding heavy dependencies, or promising DOCX/EPUB fidelity before evidence exists | Use the existing renderer; HTML-escape rendered text/metadata; do not log raw text; keep live runtime data, public routes, production dependencies and user-facing/publisher scope in separate owner-approved issues; run DOCX/EPUB renderer spikes before fidelity claims | Architect / Reviewer | Open |

## 4. Обязательные категории рисков

### Product risks

- Неясная целевая аудитория: confirmed для trusted beta users и owner/admin; paid-user ICP - TBD.
- Scope creep: High risk, потому что active docs ограничивают текущий продукт Telegram-first closed beta и TXT/DOCX/EPUB.
  FB2 из GitHub issue #23 остается deferred idea: owner decision TBD,
  authorized fixtures Unknown, dependency impact Unknown.
- Unclear MVP: Medium/High risk; MVP scope описан, and free-preview evidence
  exists for the implementation slice, but readiness не подтвержден, пока Gate B
  не закрыт.
- Success criteria: formal free beta metrics are recorded in `docs/DECISIONS.md`
  and `docs/PROJECT_BRIEF.md`. Keep hard launch guardrails separate from
  language-specific translation-quality learning metrics.

### Technical risks

- Core workflow instability: Potential/High для cancel/resume/restart/worker recovery до Gate B evidence.
- Release verification gaps: broad unittest suite exists and issue #56 recorded
  local focused/full unittest, compileall and predeploy passes for preview
  evidence, but real-file/server-smoke/restore/restart release evidence remains
  incomplete.
- CI policy: `.github/workflows/checks.yml` exists and is advisory for now.
  Local gates remain required. Current run/pass status is Unknown unless
  PR/check evidence is inspected.
- Brittle parsing/processing: High for DOCX/EPUB/TXT real files until real-file
  evidence passes. Issue #73 reduces unsafe-container risk with local synthetic
  negative fixtures, but does not prove real-file fidelity/openability.
- Background jobs: High due to leases, retries, worker loop, provider capacity and usage accounting.
- Issue #30 reduced one focused cancel/provider/admin reliability risk with
  in-process automatic result delivery idempotency, admin bulk-key-test guards,
  and provider-failure safe retry metadata tests. It does not close broad Gate B
  restart/cancel/resume evidence.
- Storage: High due to local object storage and runtime `var/`.
- Database migrations: migrations directory Not found; schema/state changes require approval.
- Concurrency/race conditions: High around scheduler claims, worker capacity, provider channels and user/job caps.
- Error handling: Medium/High; safe redaction exists but new paths must be reviewed.
- Observability: Medium; provider/admin visibility exists, but Alerts MVP and
  Backups visibility remain gaps until the issue #71-approved metadata-only
  owner report exists.

### Security risks

- Auth: High; admin auth/session/RBAC and SSH tunnel model must not be weakened.
- Permissions: Medium/Unknown for future named admins/public admin; current owner/admin model is closed beta.
- Secrets: Critical; real `.env*` files are present locally and must not be read/edited casually.
- Env files: Critical for real env files; example env files are documentation/config references only.
- User data: Critical; uploaded documents, generated files, runtime DBs and logs are sensitive.
- Raw text and prompt diagnostics: High; owner-approved permanent access exists
  only in dedicated SSH-tunneled diagnostic surfaces. Safe logs, archives,
  telemetry, normal admin pages and API surfaces must remain redacted.
- External integrations: High; Telegram and DeepSeek/provider layer affect keys, cost, auth/billing failures and user UX.
  Issue #31 reduces misleading provider-health diagnostics by classifying unsafe
  model-output failures as `unsafe_model_output` rather than auth, billing, 429,
  timeout, unavailable or malformed provider failures.

### Privacy/legal risks

- Personal data: Telegram IDs and user activity exist; keep metadata minimal and redacted.
- User files: Critical; source/intermediate/partial/final documents are stored in object storage/runtime paths.
- Legal/privacy copy: Not found as production-ready public docs; Gate D marks legal/privacy/AUP/refund docs incomplete.
- Consent/permissions: Rights confirmation is active and must not be weakened.
- Data retention: Proposed/Unknown until TTL cleanup/delete verification is implemented and evidenced.

### Payment/business risks

- Pricing: Draft only; do not treat pricing docs as production pricing.
- Billing: In-memory billing/ledger code exists, but paid beta ledger is not ready.
- Refunds: Gate C marks refund/support/reconciliation incomplete.
- Paid launch: Critical; blocked until Gate C and human approval.
- External provider costs: High; beta safety caps exist but key/concurrency/cap changes can increase spend.
- Admin bulk key probes are paused during active translations/provider requests
  by PR #38; future admin/provider changes must not remove that guard without
  owner approval and focused tests.

If a payment/provider/business zone is not implemented as a production-ready path, mark it Not found / Unknown rather than inventing readiness.

### Operational risks

- Deployment: Critical; Docker Compose VPS model exists, but production deployment requires approval.
- Rollback: High; restore runbook exists, but release gates still require restore rehearsal evidence.
- Monitoring: Medium/High; admin live/provider visibility exists, but full monitoring/alerts are not complete.
- Backups: High; scripts/runbooks exist, but backup visibility and restore rehearsal remain Gate B gaps.
- Incident response: Gate D item; Unknown/Needs decision for public production.
- Support workflow: Gate D item; Unknown/Needs decision.

### AI-agent workflow risks

- Agents changing too much: High; use small focused diffs and Orchestrator split.
- Agents modifying high-risk files: High; require human approval for secrets, env, deployment, payments, auth/security, legal/privacy, user data and migrations.
- Agents hallucinating docs: Medium; docs must separate confirmed facts, assumptions, TBD and Unknown.
- Agents skipping tests: Medium; final reports must list tests run or explain docs-only/no tests.
- Agents creating conflicting PRs: Medium; avoid parallel edits to shared state machines and contracts.
- Agents bypassing or drifting from skill dispatch: Medium; final reports should
  include routing receipts, supporting skills should stay minimal and justified,
  and Reviewer should check route/approval consistency against `AGENTS.md` and
  `docs/AGENT_SKILL_ROUTING.md`.
- Agents weakening guardrails: High; Reviewer must check safety/privacy/payment/deployment guardrails explicitly.
- Admin redesign scope creep: Medium; the Beta Operations Console should remain
  incident-first, read-only by default and split into small issues rather than
  becoming a broad admin rewrite.
- Internal reader scope creep: Medium; the before-after reader should remain a
  local internal/dev QA tool for approved fixtures until separate owner-approved
  issues cover user-facing access, publisher workspace, admin routes, runtime
  data access, production dependencies or DOCX/EPUB fidelity claims.

## 5. Human approval required

- Area: Secrets and real env files.
  Why approval is required: keys/passwords/tokens can compromise Telegram, DeepSeek, admin, Postgres and user data.
  What must be reviewed: exact file/path, whether real secret exposure happened, masking/rotation impact.
  Minimum evidence before approval: no real secret in diff/logs, reason for access, rollback/rotation plan if exposure is possible.

- Area: Deployment, Docker, server scripts and production operations.
  Why approval is required: can change availability, network exposure, runtime mounts, backups and server state.
  What must be reviewed: compose/service changes, env contract, smoke checks, rollback and backup status.
  Minimum evidence before approval: `scripts/predeploy_check.sh` plan/result where applicable, target server scope, rollback path.

- Area: Auth, security, admin exposure, RBAC and secret storage.
  Why approval is required: can expose admin console or weaken access/redaction.
  What must be reviewed: auth/session/CSRF/RBAC, bind address, admin routes/views, redaction tests.
  Minimum evidence before approval: targeted auth/security/admin tests, no public admin exposure, no raw text/secrets leakage.

- Area: User data, storage, retention, TTL, backup/restore and destructive operations.
  Why approval is required: affects uploaded documents, generated outputs, runtime DBs, logs and recoverability.
  What must be reviewed: data classes touched, delete/retention semantics,
  backup/restore impact, safe metadata rules and whether raw text remains
  confined to the approved owner-only diagnostic surface.
  Minimum evidence before approval: dry run or test fixtures, backup status,
  restore/rollback path, privacy-safe logs and redaction coverage for
  non-diagnostic admin/archive/API surfaces.

- Area: Database schema/state, scheduler/job/work-unit state.
  Why approval is required: durable state correctness affects accepted jobs and restart recovery.
  What must be reviewed: schema compatibility, migration/forward-fix plan, scheduler/worker tests, backup impact.
  Minimum evidence before approval: targeted DB/scheduler tests, rollback or forward migration plan, release-gate impact.

- Area: Payments, pricing, billing, refunds and paid launch.
  Why approval is required: paid beta is explicitly blocked until Gate C.
  What must be reviewed: payment provider flow, ledger/idempotency, refunds, reconciliation, support policy, pricing snapshot.
  Minimum evidence before approval: Gate C plan, tests for payment events and idempotency, owner-approved policy.

- Area: Legal/privacy/AUP/refund/support copy.
  Why approval is required: users upload rights-sensitive documents and public claims create legal/privacy exposure.
  What must be reviewed: exact copy, scope of claims, retention promises, consent/rights wording, support/refund commitments.
  Minimum evidence before approval: owner/counsel decision or explicit TBD; no invented production policy.

- Area: New production dependencies.
  Why approval is required: dependencies affect deploy, licensing, security and maintenance.
  What must be reviewed: package purpose, alternatives, license/security implications, deploy impact.
  Minimum evidence before approval: minimal dependency rationale, install/test plan, rollback/removal plan.

## 6. Mitigation backlog

- Task: Создать Gate B evidence report.
  Risk reduced: R-003, R-005, R-008, R-027.
  Priority: High.
  Suggested owner: Reviewer.
  Acceptance criteria: pass/fail/deferral table for every Gate B item with commands, artifacts and owner decision.

- Task: Утвердить beta success metrics.
  Risk reduced: R-004.
  Priority: Medium.
  Suggested owner: Human / Scribe.
  Status: Done 2026-05-17.
  Acceptance criteria: 3-5 metrics recorded in active docs, with Unknown/TBD removed where decided.

- Task: Выполнить authorized real-file TXT/DOCX/EPUB matrix.
  Risk reduced: R-008, R-014.
  Priority: High.
  Suggested owner: Reviewer.
  Acceptance criteria: fixture manifest with rights basis, pass/fail report,
  DOCX openability notes using local LibreOffice Writer and the approved
  no-repair/no-blocker threshold, local/offline EPUBCheck output, no raw text in
  logs/admin.

- Task: Добавить или проверить negative upload fixtures.
  Risk reduced: R-009, R-014, R-034.
  Priority: High.
  Suggested owner: Architect / Implementer / Reviewer.
  Acceptance criteria: tests for wrong extension, traversal, oversize, corrupt ZIP and zip-bomb-like fixture; safe user errors; quarantine/files do not reach workers.
  Status: Done 2026-05-28 by issue #73 for local synthetic fixtures. Remaining
  related blockers: TTL/quarantine cleanup, real-file QA and approved
  beta-server smoke.

- Task: Design local malware/AV scanning gate.
  Risk reduced: R-009, R-014, R-020, R-034.
  Priority: High.
  Suggested owner: Architect / Human.
  Acceptance criteria: scanner contract, verdict taxonomy, quarantine state
  transitions, fail-closed beta behavior, safe metadata fields, ClamAV/local
  deployment implications and public-external-scanning guardrails are recorded
  before implementation.

- Task: Implement scanner contract and local scanner adapter in separate PRs.
  Risk reduced: R-009, R-014, R-020, R-034.
  Priority: High.
  Suggested owner: Implementer / Reviewer.
  Acceptance criteria: unscanned/infected/error files never reach parser or
  translation workers; EICAR or equivalent safe fixture is detected; scanner
  timeout/unavailable/error behavior is tested; logs/admin contain metadata
  only.

- Task: Run FB2 idea intake only if owner wants to revisit issue #23.
  Risk reduced: R-002, R-008, R-009, R-014.
  Priority: Low / deferred.
  Suggested owner: Human / Architect.
  Acceptance criteria: owner decision recorded; supported FB2 subset, authorized
  fixture rights basis, dependency impact, parser/resource safety constraints
  and verification plan are defined before any implementation issue exists.

- Task: Спроектировать TTL cleanup/delete verification.
  Risk reduced: R-010, R-020, R-023.
  Priority: High.
  Suggested owner: Architect / Human.
  Acceptance criteria: approved data-retention plan, idempotent cleanup behavior, tests, backup/restore impact note.
  Decision status: issue #71 approved verification on synthetic data by default
  and only owner-approved disposable beta/runtime copies for any second pass; no
  live beta/server cleanup checks.

- Task: Запустить release-scoped verification before release decisions.
  Risk reduced: R-006, R-031.
  Priority: High.
  Suggested owner: Reviewer.
  Acceptance criteria: recorded output summary for `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall src`, `scripts/predeploy_check.sh`.

- Task: Decide CI policy.
  Risk reduced: R-007, R-031.
  Priority: Medium.
  Suggested owner: Human / Architect.
  Status: Done 2026-05-17.
  Acceptance criteria: decision recorded: current GitHub Actions workflow is advisory or required, expansion scope is approved if needed, and agents keep CI pass status Unknown unless visible check evidence exists.

- Task: Restore rehearsal from a real backup artifact.
  Risk reduced: R-027.
  Priority: High.
  Suggested owner: Human / Reviewer.
  Acceptance criteria: `scripts/verify_backup_export.py` passes, restore runbook acceptance criteria are recorded, no raw document text appears in logs/admin.
  Decision status: issue #71 approved backup/restore evidence only in
  owner-approved disposable/local/test/copy environments or explicitly approved
  beta environment; live beta/server data requires exact-run owner approval;
  artifacts are metadata-only.

- Task: Add metadata-only Alerts/Backups owner runbook report.
  Risk reduced: R-015, R-028.
  Priority: Medium.
  Suggested owner: Implementer / Reviewer.
  Decision status: issue #71 approved owner report for Gate B and admin UI
  later.
  Acceptance criteria: provider, queue/worker, disk/storage, failed-job and
  backup/restore status visible or documented; no raw document text, prompts,
  translations, API keys, stack traces, backup archives or restored files.

- Task: Implement Beta Operations Console redesign in small slices.
  Risk reduced: R-015, R-028, R-036.
  Priority: High before free closed beta.
  Suggested owner: Orchestrator / Architect / Implementer / Reviewer.
  Decision status: owner approved the design direction on 2026-05-31; design is
  recorded in
  `docs/superpowers/specs/2026-05-31-beta-operations-console-redesign.md`.
  Acceptance criteria: first slice provides Translation Failure Trace and a
  safe evidence packet; provider/key incident clarity follows; overview triage
  links to trace views; state-changing admin actions remain deeper and clearly
  classified; the approved owner-only raw Text diagnostics view remains
  available; no additional raw document text, prompts, translations, API keys,
  stack traces, public admin exposure, payment readiness or
  production-readiness claims are introduced.

- Task: Define paid-beta plan only when owner chooses Gate C work.
  Risk reduced: R-024.
  Priority: Medium.
  Suggested owner: Architect / Human.
  Acceptance criteria: Stars/XTR, ledger, idempotency, refunds, `/paysupport`, reconciliation and support policy have approved design and tests.

- Task: Create AI-agent high-risk file preflight checklist in task templates.
  Risk reduced: R-029, R-030, R-032.
  Priority: Low.
  Suggested owner: Scribe / Reviewer.
  Acceptance criteria: agents explicitly list high-risk touched files, approvals, tests and conflicts before implementation.

## 7. Reviewer checklist for risks

- Проверить high-risk files: secrets/env, deployment, payments/pricing, auth/security, legal/privacy, user data, database/state, external integrations.
- Проверить tests: relevant focused tests, full suite/predeploy when scope is broad or release-adjacent, and honest "not run" note for docs-only work.
- Проверить docs: no invented features, CI, deployment steps, production readiness or legal/privacy/payment claims.
- Проверить security/privacy/legal/payment/deployment: no weakened guardrails,
  no raw text outside approved owner-only diagnostics, no secrets, no public
  admin, no paid flow before Gate C.
- Проверить unintended behavior changes: bot flow, rights confirmation, scheduler/job state, storage paths, provider/cost caps and admin redaction.
- Проверить approvals: High/Critical zones must have explicit human approval before changes.
- Проверить parallel conflicts: shared state machines, bot/backend contracts, provider/admin telemetry, auth/admin views and deployment docs/scripts.

## 8. Architect checklist for risks

- Определить affected systems: bot, backend/API, admin, worker/scheduler, storage, DB, provider layer, deployment, docs.
- Определить rollback: config rollback, code revert, data restore, disable switch, provider circuit/cap reset or manual recovery.
- Определить tests: focused tests, full suite, compileall, predeploy, server smoke, real-file matrix, backup/restore rehearsal.
- Определить approvals: human owner approval for High/Critical zones before file changes or operations.
- Определить параллельные конфликты: state machine ownership, bot/backend contracts, admin/provider telemetry, auth/RBAC/admin routes, file adapters/assembly/tests, deployment/scripts/runbooks.
- Определить release gate impact: Gate A/B/C/D item touched, evidence required, and whether a signed deferral is acceptable.
- Определить data/privacy impact: raw text, prompts, translations, secrets, runtime files, retention and backup scope.
