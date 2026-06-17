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
| R-002 | Scope creep за пределы TXT/DOCX/EPUB, Telegram-first и closed beta | Product | High | `README.md`, `README.project.md`, `docs/DECISIONS.md`, `docs/PROJECT_BRIEF.md` запрещают PDF/OCR/MOBI/FB2/public SaaS сейчас; RTF #4, FB2 #23 and next-format prioritization #208 are committed future roadmap, not current MVP implementation | Раздувание QA, security, support и parser surface | Любое расширение форматов/каналов только через Architect plan, fixture rights basis, dependency review, verification plan and human approval | Human / Architect | Open |
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
| R-021 | Legal/privacy/AUP/refund/support text is not production-ready | Privacy / Legal | High | Gate D unchecked: legal/privacy/AUP/refund docs; `docs/DECISIONS.md` says public production not ready; issue #207 records release-version analytics/consent behavior as TBD | Agents may invent policy or public claims, especially around analytics file use | Use TBD/Unknown; owner/counsel approval before public/legal copy; do not claim release-version analytics consent/readiness until #207 is decided | Human / Scribe | Needs decision |
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
| R-037 | Owner-only raw text, prompt diagnostics and full diagnostic archives can leak sensitive user/provider context if copied or exposed outside admin | Privacy / User data / Admin | High | Owner approved permanent raw translation text diagnostics on 2026-06-01, raw prompt viewing in a dedicated owner-only diagnostic surface on 2026-06-02, owner-only downloaded full diagnostic archives with `raw_text_diagnostics.json` on 2026-06-07, run-scoped `provider_io_diagnostics.jsonl` with exact DeepSeek request JSON bodies and raw response bodies on 2026-06-07, `diagnostic_files/` copies of original uploaded files plus final/partial translated result files on 2026-06-14, issue #549 `glossary_runtime_diagnostics.json` archive sidecars for glossary runtime diagnostics on 2026-06-14, issue #612 prepared-glossary package status/linkage metadata inside that same owner-only sidecar on 2026-06-15, and issue #645 automatic-glossary policy/attachment/prep/beta-safety/fallback/cache/compliance metadata in the same owner-only sidecar on 2026-06-15; branch `codex/internal-reader-v2` adds a run-log Translation Reader using the same owner-only diagnostic boundary; issue #268 adds a run-scoped owner-only raw diagnostic sidecar for marked Reader source/translation fragments; normal details, telemetry and APIs remain redacted/metadata-only | Screenshots, copied excerpts, downloaded diagnostic archives, support notes, PRs/issues, public admin exposure, persisted review sidecars or broadened routes could leak source text, translated output, original/result file bytes, glossary prompt context, prepared-package metadata, selected glossary metadata, prompt bodies or raw provider output | Keep diagnostic routes and downloaded full diagnostic archives SSH-tunneled and owner-only; do not include raw excerpts, raw file bytes or raw diagnostic archives in docs/issues/PRs/support notes without exact owner approval; keep telemetry/normal admin/API surfaces redacted; exclude provider `Authorization` headers, API keys, tokens, DSNs, real `.env*` values and raw glossary/prep fields from provider IO/glossary archive diagnostics; require review for new raw-text, raw-file, raw-prompt, raw-provider or glossary diagnostic surfaces | Human / Architect / Reviewer | Open |
| R-038 | Internal before-after reader can expand into raw-text admin/user access or overclaim format fidelity | QA / Privacy / Product | Medium | Owner approved `docs/superpowers/specs/2026-06-01-internal-before-after-reader-design.md` as an internal/dev design direction only; issue #199 approves a narrow owner-only internal admin UI; branch `codex/internal-reader-v2` adds a separate run-scoped diagnostic reader from logs/details/Text diagnostics; scope still excludes live `var/`, public routes, user-facing reader, publisher workspace, production dependencies and DOCX full-fidelity claims | A useful QA tool could drift into exposing source/translation text through admin/logs/artifacts, reading live user data, adding heavy dependencies, or promising DOCX/EPUB fidelity before evidence exists | Use existing renderer/work-unit paths; HTML-escape rendered text/metadata; do not log raw text; keep live runtime data, public routes, raw-text APIs or archive exports beyond the approved owner-only full diagnostic download, production dependencies and user-facing/publisher scope in separate owner-approved issues; run DOCX/EPUB renderer spikes before fidelity claims | Architect / Reviewer | Open |
| R-039 | Analytics/product-improvement file use can become unclear or overclaimed | Privacy / User data / Legal | High | Owner approved current/pre-release internal use of all uploaded files for analytics/product improvement on 2026-06-02; issue #207 records release-version behavior as TBD | User documents or translated output could be used, retained, copied or described without clear release-version policy, consent, retention or legal/privacy boundaries | Keep current owner decision explicit; use #207 for release-version policy; do not add public/legal/privacy claims, consent UI, retention changes or analytics implementation without separate approval and review | Human / Architect / Scribe | Open |
| R-040 | Pre-release automatic full raw provider diagnostics can become accidental release telemetry | Privacy / User data / Provider diagnostics | High | Owner approved broad automatic raw diagnostic capture for pre-release development on 2026-06-06 after job `job-9488146309f7434b9746580a6cc22d96` could not be fully diagnosed from safe metadata because raw provider output was not persisted | Source text, prompts, provider payloads, raw outputs and translations may accumulate in runtime artifacts; future agents could mistake this for release-version consent, support workflow or public/privacy-ready analytics | Keep the decision explicitly pre-release and owner-only; exclude secrets; require focused Architect/Reviewer pass for implementation; require Release Readiness to revisit and narrow/replace this policy before free beta/public release | Human / Architect / Reviewer / Release Readiness | Open |
| R-041 | Complex book glossary/profile/DeepSeek Pro diagnostics can become unbounded or over-trusted | Translation architecture / Privacy / Provider diagnostics | High | Owner approved the complex glossary/profile/Pro direction on 2026-06-12 in `docs/DECISIONS.md`; discovery note `docs/superpowers/specs/2026-06-07-book-glossary-system-discovery.md` records glossary-by-default, book profile, Pro roles, broad pre-release diagnostics and release privacy as TBD; issue #413 report `docs/superpowers/specs/2026-06-12-deepseek-pro-glossary-profile-spike-report.md` records that bounded live `deepseek-v4-pro` role calls validated profile-advisor JSON but failed larger glossary-editor JSON and exceeded the observed token cap; issue #449 report `docs/superpowers/specs/2026-06-12-reduced-glossary-editor-retry-report.md` records mixed reduced-packet live evidence: Russian `length`/invalid JSON, Ukrainian timeout with usage `Unknown`, and successful sample/EPUB validation; issue #451 report `docs/superpowers/specs/2026-06-12-reduced-glossary-runtime-go-no-go.md` records NO-GO for normal runtime prompt integration now; issue #463 report `docs/superpowers/specs/2026-06-13-reduced-glossary-readiness-after-packet-fixes.md` records post-#461/#462 local/fake structural passes but default readiness failures on low-confidence warning/needs-review outputs and approved EPUB reducer diagnostic/drop pressure; issue #464 report `docs/superpowers/specs/2026-06-13-reduced-glossary-editor-post-fix-retry-report.md` records an explicit owner gate deferral and a bounded post-fix provider retry where all four approved packets validated with provider usage present, while merge findings still had warning-only duplicate/low-confidence semantic findings; issue #465 report `docs/superpowers/specs/2026-06-13-glossary-runtime-cache-policy-decision.md` records first-adapter cache bypass for glossary-injected enabled/test-path units, with compact signatures metadata-only; issue #466 / #204AH adds a disabled-by-default prompt-policy adapter decision contract that keeps normal prompts unchanged and falls back for unready glossary metadata; issue #477 report `docs/superpowers/specs/2026-06-13-glossary-runtime-provider-smoke-report.md` records that bounded runtime smoke validated three TXT calls but failed approved EPUB RU/UK calls with provider `length` and local `truncated_output`/`external_text`; issue #487 adds local metadata-only runtime pressure summaries; issue #488 adds a disabled/test-only high-pressure EPUB fallback that omits glossary prompt context and records compact reason codes under conservative local thresholds; issue #489 adds local completion-first EPUB selector/context budget tuning with metadata-only reason codes; issue #490 adds fake/local paired EPUB glossary-on/off rehearsal metadata without quality claims; issue #491 records a bounded paired live EPUB smoke where all four glossary-on/off calls failed with provider `length` and local `truncated_output`/`external_text`; issue #492 records metadata-only `FAIL` for runtime rollout readiness, limited-beta readiness, owner-only battle-test candidacy and positive glossary quality claims from the current EPUB evidence; issue #501 / #204AV adds a default-off owner-only local preflight so bounded runtime glossary context is injected only for useful READY units with source term/alias presence, target metadata and local pressure/budget pass; issue #503 / #204AW adds a local-only EPUB runtime unit/output-budget selector that chooses only #501-style glossary-useful, pressure-safe EPUB units or emits metadata-only skip/fallback reasons; issue #505 / #204AX adds a default-off owner-only approved target-metadata fixture overlay for the committed control EPUB fake/local path, with raw/prompt/provider/key field rejection and metadata-only fallback; issue #507 / #204AY adds an explicit post-#505 control-EPUB paired smoke boundary, fake/dry preflight and bounded live provider smoke that validated all four paired calls for the control EPUB unit, while translation quality remains `Unknown`; issue #551 repairs the temporary battle-test evidence path so scheduled/external worker `with_glossary` units either use per-work-unit READY hook data or record metadata-only fallback/omission diagnostics for the owner-only archive sidecar; issue #593 records a fresh post-#591/#594 adversarial TXT live rerun with clean useful-entry filtering and structural validation, but remaining target-form compliance findings (`ru` 2/5 present, `uk` 4/5 present); issue #596 adds local binding target-form wording and `mandatory_term` markers to the default-off formatter contract; issue #601 expands the committed synthetic adversarial target-variant fixture after owner-only #593 QA; issue #600 records the post-#596/#601 bounded adversarial TXT live rerun where 4 approved calls completed, structural validation passed, glossary-on configured-form compliance passed for `ru` and `uk` (5/5 each), glossary-off remained baseline, and no secret-pattern findings were detected; issue #608 records the no-code pre-Telegram battle-test architecture for a job-scoped compact prepared-glossary package, keeping `deepseek-v4-pro` glossary-prep only and runtime translation on the configured runtime model; issue #610 adds the local-only prepared package validator with raw/secret rejection and #556 overlay compatibility; issue #611 adds a no-schema worker/#557 handoff for #610-validated READY packages on explicit `with_glossary` owner/test paths only, with metadata-only fallback and no provider/job-schema/admin/storage/rollout/cache-reuse side effects; issue #633 adds the default-off owner/test Telegram job-creation bridge that can attach a deterministic-match #610 READY compact package to `translation_policy.prepared_glossary_package` for the existing #611 worker path; issue #436 records release-version glossary/profile diagnostic privacy, consent, retention, deletion, support and legal/privacy policy as `TBD`/blocking | Glossary/profile facts can steer an entire book incorrectly; model roles may contradict each other; local code cannot prove semantic truth; raw glossary/profile/prompt/provider/QA artifacts can accumulate; future agents may confuse pre-release diagnostics with release-ready telemetry or add expensive provider loops without failure boundaries; token estimates can under-reserve against provider-reported usage; cache reuse can preserve stale non-glossary translations if glossary/profile dimensions are incomplete; glossary runtime prompts can still overrun or truncate on EPUB units if fallback/tuning evidence is over-trusted; current EPUB live evidence still fails even when glossary context is omitted; provider can structurally validate yet miss configured target forms even when selection/filtering is clean; real Telegram `with_glossary` can still be fallback-only if prepared target metadata is missing, not READY or not attached to the job policy | Treat #204 as architecture/discovery before implementation; require explicit role graph/contracts, schema/enums, evidence/confidence fields, fallback behavior, translation snapshot boundaries, diagnostics ownership and evaluation plan; keep secrets excluded; keep release-version privacy/retention/consent/deletion/support/legal policy `TBD`/blocking until exact owner approval and Release Readiness review; require conservative token reservation and fresh exact approval for any further live provider spike; do not enable normal runtime glossary prompts until provider/cache/diagnostics gates pass; treat #464, #477, #487-#492, #507 and #593 fake/dry/live bounded results as provider-boundary, local test-path or metadata-only decision evidence only, not normal runtime integration approval; keep #501 default-off/owner-only and metadata-only, with non-useful battle-test units falling back to the existing non-glossary cache path; treat #503 as local selector/fallback evidence only and #505 as local target-metadata fixture evidence only, not provider-smoke success, semantic-quality proof or rollout approval; treat #551 as evidence repair only, not quality proof or rollout approval; treat #600 as narrow synthetic TXT provider-boundary evidence that improves configured-form compliance confidence but does not prove real-book/EPUB quality, morphology, rollout, cache reuse or release readiness; treat #608/#610/#611/#633 as local package architecture, validation and handoff/attachment evidence only until a separately approved owner-assisted Telegram test produces reviewed evidence; keep #466 disabled-by-default and split future normal prompt rollout, fresh live EPUB provider smoke, or glossary-aware cache keys into separately approved issues | Human / Architect / Reviewer / Release Readiness | Open |
| R-042 | Glossary/profile diagnostic sidecars can become an accidental raw user-document retention/export system | Privacy / User data / Admin diagnostics | High | Issue #412 / #204I design package `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md` defines a dedicated owner-only sidecar boundary, raw-field manifest and retention/export/deletion TBDs; issue #434 implements only the owner-only sidecar foundation and boundary tests; issue #436 keeps release-version retention/export/deletion/support/legal policy `TBD`/blocking; issue #549 adds `glossary_runtime_diagnostics.json` only inside owner-only downloaded full diagnostic archives when glossary runtime diagnostic data exists; issue #551 adds scheduled/external worker fallback/injection metadata events that feed that owner-only sidecar without placing raw source text, prompt bodies or provider responses in ordinary events; issue #612 adds prepared-package status/linkage metadata to the same owner-only archive sidecar and hardens glossary adapter event redaction; issue #645 extends the same sidecar for automatic default runs with policy, attachment/prep, beta-safety, fallback/cache and compliance metadata while preserving secret/raw rejection | Raw candidates, evidence snippets, prompts, provider outputs, translated excerpts, rendered glossary prompt context, prepared-package metadata or owner notes could leak into ordinary logs/admin/API/support/release artifacts, or be retained/exported without consent/deletion policy | Keep sidecars dedicated and owner-only; require explicit manifest/secret rejection for raw-capable fields; forbid secrets/auth material; keep ordinary logs/telemetry/admin trace/API metadata-only; require separate approval for broader admin/runtime/export/retention/delete/support/legal behavior; coordinate release-version policy with #207 and Release Readiness | Human / Architect / Reviewer / Release Readiness | Open |

## 4. Обязательные категории рисков

R-041 update note, 2026-06-15: issue #614 adds metadata-only bounded live
DeepSeek Pro prepared-glossary evidence after #619 fake/dry passed. One
approved live call completed within caps, but the response omitted required
top-level prepared-package fields and failed #610 validation. Treat #614 as
provider-boundary failure evidence only: #607 remains blocked until a READY
live prepared package exists, and rollout/cache/release claims remain
unapproved.

R-041 update note, 2026-06-15: issue #622 adds a local-only package-envelope
hardening step for the #614 runner. The envelope may fill only locally known
package metadata around provider-supplied entries and must still pass #610
validation. It does not approve local semantic inference, live retries,
runtime translation, rollout, cache reuse or release/privacy claims.

R-041 update note, 2026-06-15: issue #626 adds a conservative local unwrap for
the #624 observed single-key `output_package_skeleton` provider wrapper. The
unwrap still runs #622 boundary checks and #610 validation, and does not
approve semantic inference, live retries, runtime translation, rollout, cache
reuse or release/privacy claims.

R-041 update note, 2026-06-15: issue #628 treats prompt-placeholder or
`Unknown` values in locally owned prepared-package metadata as missing local
envelope fields. This improves package identity before #607 but does not
approve semantic inference, live retries, runtime translation, rollout, cache
reuse or release/privacy claims.

R-041 update note, 2026-06-15: issue #630 enriches local-envelope prepared
entries from the approved preflight packet for source-side fields only, while
preserving provider-supplied target metadata. A post-#630 bounded #624 live
retry produced a #610 `ready` package for the approved committed Gutenberg
control EPUB targeting `ru` with 8 ready entries, 0 `needs_review` entries, 1
live call and 9,776 provider-reported tokens. Treat this as provider-boundary
evidence that can inform the owner-assisted #607 Telegram battle-test, not as
translation quality proof, default rollout approval, cache reuse approval or
release/privacy/legal/support readiness.

R-041 update note, 2026-06-15: issue #633 adds the default-off owner/test
Telegram job-creation bridge for prepared packages. Explicit `with_glossary`
jobs can attach only a deterministic-match #610 READY compact package to
`translation_policy.prepared_glossary_package`; default and `without_glossary`
jobs remain unchanged, and missing/invalid/non-matching packages fall back with
metadata-only reason codes. Treat this as local handoff evidence only, not
Telegram operation by Codex, rollout approval, cache reuse approval, live
provider evidence or glossary quality proof.

R-041 update note, 2026-06-15: issue #635 wires the #633 bridge through
`BotRuntimeConfig` / `build_translation_service` only for an explicitly injected
owner/test prepared-package resolver. Focused fake/local evidence proves that a
queued Telegram job policy can carry a matching #610 READY package into the
existing #611 worker/#557 resolver path and render glossary context with #465
cache bypass. This still adds no package registry, storage/config source,
live provider work, Telegram operation by Codex, rollout, cache reuse or
release/privacy/legal/support readiness.

R-041 update note, 2026-06-15: issue #637 adds a default-off local/fake
owner/test prepared-glossary prep resolver boundary for explicit
`with_glossary` jobs. The resolver receives pending upload content in memory
and may return only a #610 READY compact package matched through #635; default
and `without_glossary` jobs do not call prep. Configured prep failures fail
closed before persistent queueing with metadata-only reason codes. This still
adds no live provider calls, package registry, durable storage/retention,
Telegram operation by Codex, rollout, cache reuse or release/privacy/legal/
support readiness.

R-041 update note, 2026-06-15: issue #640 records the owner-approved #639
policy that the temporary Telegram glossary selector is superseded by automatic
internal glossary preparation/injection for supported Telegram jobs. Treat #640
as a policy/docs change only: code removal/default integration is split across
#641-#645 and #648, and #646 later ran as a bounded live smoke after local/fake
gates and produced failed/no-go evidence. This does not approve
glossary-aware cache reuse, provider config/key changes, deployment, durable
DB/schema/state/storage/admin/retention/export/delete changes or
release/privacy/legal/support readiness.

R-041 update note, 2026-06-15: issue #641 removes the user-facing Telegram
glossary selector from the normal flow and defaults new supported job metadata
to the internal automatic glossary policy, while preserving explicit legacy
`without_glossary` compatibility. This is a UX/policy-metadata step only: it
does not prove glossary quality, run live provider calls, approve cache reuse,
change provider config/secrets, mutate DB/schema/storage/admin/retention, or
make release/privacy/legal/support readiness claims.

R-041 update note, 2026-06-15: issue #642 adds a reusable local/fake
prepared-glossary prep service for automatic job setup. The service builds
local scanner/profile/reducer packets from pending upload content and validates
injected fake/local provider output through #610 before returning a compact
attachment or metadata-only fallback. Treat this as a local contract and fake
provider boundary only: live provider calls, provider config/key changes,
cache reuse, DB/schema/state/storage/admin/retention changes, Telegram
operation and release/privacy/legal/support claims remain unapproved.

R-041 update note, 2026-06-15: issue #643 gates configured automatic
prepared-glossary prep resolver calls through the existing beta-safety
cost/cap guard before the resolver can run. Missing beta-safety guard,
kill-switch/cap denial or missing provider usage evidence produces
metadata-only reason codes; provider usage is recorded when supplied, otherwise
the conservative estimate is accounted while provider-reported usage remains
`Unknown`. Treat this as a cost-control and metadata boundary only: it does not
approve live provider calls, payment/billing semantics, provider config/key
changes, cache reuse, DB/schema/state/storage/admin/retention changes,
deployment or release/privacy/legal/support claims.

R-041 update note, 2026-06-15: issue #644 generalizes the prepared-package
runtime resolver from EPUB-only to supported persistent TXT/DOCX/EPUB units.
The generic path still validates #610 compact packages, applies target metadata
through the approved overlay boundary, requires source term/alias presence and
budget-safe prompt context, and keeps #465 cache bypass only for injected
units. Treat this as local/fake runtime plumbing only: it does not approve live
provider calls, cache reuse, provider config/key changes, DB/schema/state/
storage/admin/retention changes, deployment, or release/privacy/legal/support
claims.

R-041 update note, 2026-06-15: issue #645 extends the owner-only downloaded
`glossary_runtime_diagnostics.json` sidecar for automatic default glossary runs
with automatic-policy, prepared-package attachment/prep, prep beta-safety,
target-metadata, fallback/cache and metadata-only compliance summaries. Treat
this as diagnostics/readability plumbing only: it does not approve live
provider calls, rollout, cache reuse, provider config/key changes,
DB/schema/state/storage/admin-auth/retention/export/delete changes, deployment
or release/privacy/legal/support claims.

R-041 update note, 2026-06-16: issue #648 adds a DeepSeek-compatible
prepared-glossary provider adapter and explicit runtime config wiring for the
#642/#643 prep service. Fake-provider tests cover READY attachment through
worker injection, provider usage/cap enforcement, invalid JSON/schema,
target mismatch and raw/secret metadata failure paths. Issue #659 then wires
`bot_runtime_config_from_settings()` to build that provider through the existing
DeepSeek runtime channel pool when channels are available and marks no-package
`with_glossary` runs with high-severity `not_effective` metadata instead of
leaving them as silent glossary-looking fallbacks. Treat this as
provider-boundary wiring and diagnostic evidence only: #646 remains the first
bounded live smoke gate. Cache reuse, provider config/key changes,
DB/schema/state/storage/admin/retention changes, deployment and
release/privacy/legal/support claims remain unapproved.

R-041 update note, 2026-06-16: issue #656 fixes a #646 fake/dry local blocker
by preserving #610 prepared package source refs and allowing the persistent
resolver to build source-present, target-backed runtime glossary entries
directly from READY prepared package entries when work-unit/source-block refs
match. Treat this as local/default-off owner/test resolver plumbing only: it
does not approve live provider calls, Telegram operation by Codex, rollout,
cache reuse, provider config/key changes, DB/schema/state/storage/admin/
retention/export/delete changes, deployment or release/privacy/legal/support
claims.

R-041 update note, 2026-06-16: issue #646 bounded live automatic-default
glossary smoke ran after #641-#645, #648 and #656 plus a passing fake/dry
unit-selection preflight. The final metadata-only report records failed/no-go
evidence: `ru` prep returned HTTP 200 but failed #610 READY validation with
`prepared_glossary_package_needs_review`, while `uk` prep returned READY,
rendered glossary context and used #465 cache bypass, but runtime structural
validation failed with `block_count_mismatch`. Treat #646 as provider-boundary
failure evidence only; successful automatic live-smoke evidence, broader
default confidence, cache reuse, deployment and release/privacy/legal/support
claims remain unapproved.

R-041 update note, 2026-06-17: issue #663 adds a local/default-safe prepared
glossary candidate-quality policy before prepared-glossary prep packets reach
fake/provider boundaries. Obvious pronoun/function-word/common-phrase and
chapter/frontmatter boilerplate candidates are dropped, low-value aliases are
pruned, and all-dropped candidate sets fall back before provider invocation
with metadata-only reason codes. Treat this as prep-input risk reduction only:
it does not rewrite the scanner, prove semantic/literary quality, call live
providers, approve rollout/cache reuse/provider config/storage/admin/retention
changes or replace #664 package-level READY enforcement and #665 local audit
evidence.

R-041 update note, 2026-06-17: issue #664 reuses the #663 candidate-quality
policy inside #610 prepared package validation so structurally valid
all-low-value packages cannot become READY. Mixed packages keep valid durable
entries and report quality drops through metadata-only `quality` counts/reason
codes. Treat this as local package-adjudication risk reduction only: it keeps
raw/secret rejection and structural invalid semantics separate, and still does
not prove glossary quality, approve live provider calls, rollout, cache reuse,
provider config, storage/admin/retention changes or release/privacy/legal/
support claims. #665 local audit evidence remains required.

R-041 update note, 2026-06-17: issue #665 adds and runs a local metadata-only
prepared glossary candidate-quality audit over committed fixtures after #663
and #664. The first fake/local audit recorded 20 prep input candidates, 18
selected after prep-input quality filtering, 2 dropped, 18 package-selected
entries, 0 package-level drops, 3 ready fake/local cases and low-value rate
0.1. Treat this as deterministic local audit evidence only: provider behavior,
real-book translation quality, scanner-v2 need, rollout, cache reuse and
release/privacy/legal/support readiness remain Unknown/TBD until separately
reviewed.

R-041 update note, 2026-06-17: issue #666 records a no-code architecture
verdict to keep scanner v1 plus #663/#664 candidate-quality gates for now and
defer scanner v2. This reduces rewrite/signature churn risk in the short term,
but does not close broader scanner coverage, provider behavior or real-book
translation quality risks. Any future scanner-v2 work must be separately
approved, versioned, shadow-only first, metadata-only, and must not switch
runtime behavior, cache reuse or provider/live behavior without later approval.

### Product risks

- Неясная целевая аудитория: confirmed для trusted beta users и owner/admin; paid-user ICP - TBD.
- Scope creep: High risk, потому что active docs ограничивают текущий продукт Telegram-first closed beta и TXT/DOCX/EPUB.
  Future formats are committed roadmap scope but tracked separately: RTF #4,
  FB2 #23 and next-format prioritization #208. Implementation of any format
  beyond TXT/DOCX/EPUB needs owner implementation approval, Architect review,
  fixture rights basis, dependency review and verification plan.
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
- Analytics/product-improvement file use: High; current owner direction allows
  all uploaded files for internal/pre-release analytics, while release-version
  consent/legal/privacy behavior remains TBD in issue #207.
- Raw text, prompt and provider IO diagnostics: High; owner-approved permanent access exists
  only in dedicated SSH-tunneled diagnostic surfaces, including owner-only full
  diagnostic downloads. `provider_io_diagnostics.jsonl` may contain exact
  DeepSeek request JSON bodies and raw response bodies, but must exclude
  provider `Authorization` headers and API keys. Telemetry, normal admin pages,
  support artifacts and API surfaces must remain redacted.
- Pre-release automatic raw provider diagnostics: High; owner approved broader
  automatic capture during development only, but release-version retention,
  consent, deletion and redaction behavior remains TBD and must be revisited
  before release.
- Complex glossary/profile/DeepSeek Pro diagnostics: High; owner approved the
  complex book glossary direction for discovery/architecture, including
  glossary-by-default, book profile detection, Pro roles and broad pre-release
  diagnostics. Local validators cannot prove semantic truth, so the
  architecture must rely on evidence/confidence/review flags, role contracts
  and release-version policy review before implementation or launch claims.
  Issue #436 keeps release-version glossary/profile diagnostic consent,
  retention, deletion, support and legal/privacy policy `TBD`/blocking. The
  owner-approved 2026-06-14 glossary architecture rule keeps glossary core
  language-neutral and requires morphology, script/segmentation and
  target-language term matching to live in explicit terminology policy
  adapters; issue #517 records the no-code terminology policy registry
  architecture; issues #518-#521 add the local-only registry foundation,
  synthetic/authorized RU/UK fixture coverage, policy-aware metadata-only
  compliance summaries and opt-in compact prompt-context policy metadata; issue
  #530 records the real language-policy package acceptance matrix, evidence
  levels, fixture rules and core-neutrality proof requirements; issues #531
  and #532 add local-only policy package fixtures/tests; issue #533 records a
  metadata-only fake/dry provider-evidence protocol and package-aware preflight
  for #534; issue #534 records bounded live provider-boundary evidence with 6
  completed calls, structural validation passing, RU/UK glossary-on compliance
  passing, RU/UK glossary-off target-form-missing findings and DE on/off
  compliance passing; issue #535 records a no-code runtime rollout state
  machine that kept normal/default and limited-beta rollout rejected until a
  separate owner decision; #640 now supersedes that posture only for the
  approved #639 automatic-glossary child-issue path, while broader beta/default
  rollout, cache reuse or release/privacy/legal/support claims still require
  separate owner approval;
  issue #536 records no-code cache-key dimensions and requires bypass when any
  output-affecting glossary/profile/snapshot/selection/policy/formatter/
  fallback dimension is missing or `Unknown`; issue #537 records a
  metadata-only decision packet and keeps the recommended posture
  shadow-only/default-off until the owner chooses the next issue; issue #546
  adds a temporary Telegram per-attempt battle-test selector for manual
  with-glossary/without-glossary comparison while preserving default-off
  glossary hook gates, #465 cache bypass and metadata-only ordinary artifacts.
  Issue #555 records a no-code real-book runtime glossary resolver contract
  after the latest real EPUB `with_glossary` run showed only fallback
  diagnostics and no provider glossary context; future implementation must
  split target-metadata overlay, worker resolver, fake/local rehearsal,
  bounded live test and provider-backed preparation design into separate
  approved issues. Issue #556 adds the local-only/default-off target-metadata
  overlay contract with raw/secret rejection and source-term/alias-only
  matching; it remains a planning foundation, not arbitrary glossary
  generation, runtime rollout, provider work, cache reuse or quality proof.
  Issue #557 adds a default-off persistent EPUB resolver that reuses existing
  worker hook/preflight/cache-bypass boundaries and falls back with metadata
  reasons unless target metadata, source term/alias presence and prompt-context
  budgets pass for an explicitly enabled owner/test path. Issue #558 adds
  fake/local scheduled-worker and owner-only archive evidence for injected,
  fallback and `without_glossary` paths; this reduces wiring uncertainty but
  remains non-provider evidence. Issue #560 records a no-code provider-backed
  preparation design for arbitrary books, with durable storage,
  retention/export/delete, admin visibility and rollout still `TBD`. Issue #559
  records bounded provider-boundary evidence that glossary context can be
  injected into a real EPUB test prompt, while compliance findings show target
  metadata/selection quality still needs iteration before any rollout claim.
  Issue #567 tightens the owner-only EPUB smoke context/compliance boundary so
  rendered prompt context and compliance checks use the same target-backed
  useful entries, reducing non-useful selected-entry noise without proving
  translation quality or morphology correctness. Issue #569 hardens the
  default-off prompt-context formatter with explicit escaped source/target
  terminology contract tags for included entries, reducing prompt-shape
  ambiguity without approving rollout or proving provider obedience.
  Issue #571 records bounded owner-only evidence that, after local target
  variant adjudication, the selected Gutenberg/Oz RU EPUB glossary-on smoke
  passed structural validation and exact configured-form compliance for one
  useful entry; this reduces one provider-boundary risk but remains a narrow
  smoke result, not broad quality, morphology or rollout proof.
  Issue #574 records metadata-only owner QA for that paired Oz unit: glossary-on
  did not regress structurally and passed compliance, but glossary-off also
  happened to use an approved target-family form, so unique quality lift remains
  unproven. Issue #576 adds only an explicit #575 adversarial TXT paired-matrix
  smoke boundary with fixed allowlist, caps and diagnostics root; live provider
  behavior and broader quality remain `Unknown` until the bounded matrix is run
  and reviewed. Issue #578 tightens the #575 TXT path so prompt context and
  compliance use the same target-backed source-present useful entries, removing
  local `target_metadata_missing` / `source_term_absent` noise in fake preflight;
  post-filter live behavior remains `Unknown`. Issue #580 strengthens the
  default-off owner/test prompt-context terminology wording for included
  target-backed entries, but live provider behavior after that wording change
  remains `Unknown` until bounded rerun evidence is recorded. Issue #582 adds an
  explicit internal system-prompt acknowledgment for service-generated glossary
  context and avoids trusting raw document `<glossary_context>` tags by
  auto-detection; post-merge bounded #575 live rerun confirmed the boundary
  change reached glossary-on prompts, but exact configured target-form
  compliance remained partial (`ru` 2/5 and `uk` 4/5), so issue #584 tracks the
  next local owner/test terminology-contract strengthening step before another
  provider rerun. Issue #584 adds a compact `mandatory_term:` checklist line to
  the default-off owner/test prompt context and fake #575 preflight confirms it
  appears only in glossary-on diagnostics; issue #588 adds an explicit #586
  post-#584 adversarial TXT smoke boundary with the same #575 safeguards and a
  separate owner-only diagnostics root. Issue #586 completed the bounded
  post-#584 adversarial TXT live rerun with 4 calls, structural validation
  passing and no secret-pattern findings, but issue #591 found the run was
  affected by boundary drift: #586 did not inherit the #578 target-backed
  source-present filter and therefore checked 8 selected entries rather than
  the intended 5 useful entries. Post-#591 fake preflight removes the
  `source_term_absent` / `target_metadata_missing` noise, so a fresh bounded
  live rerun is needed before judging whether #584 improved exact configured
  target-form compliance. Rollout remains blocked pending compliance/selection
  review.
  RU/UK full morphology remains `TBD`; translation quality remains `Unknown`
  until approved owner-only review evidence exists; future policy packages must
  stay behind the explicit registry/adapter boundary, not hardcoded core
  behavior.
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

- Task: Prioritize committed future formats through issue #208.
  Risk reduced: R-002, R-008, R-009, R-014.
  Priority: Medium / later.
  Suggested owner: Human / Architect.
  Acceptance criteria: RTF (#4), FB2 (#23), PDF/OCR, HTML/HTM, ODT, legacy DOC,
  MOBI, AZW3/KPF and CBZ/CBR/DJVU are ranked; supported subsets, authorized
  fixture rights basis, dependency impact, parser/resource safety constraints
  and verification plan are defined before any implementation issue exists.

- Task: Break down complex book glossary/profile architecture through issue
  #204.
  Risk reduced: R-014, R-019, R-020, R-021, R-039, R-040, R-041.
  Priority: Medium / later until owner pulls it forward.
  Suggested owner: Human / Architect / Orchestrator.
  Acceptance criteria: issue #204 produces an architecture map, role graph,
  role contracts, schema/enums, evidence/confidence policy, book profile
  contract, translation snapshot boundary, diagnostics/retention caveats,
  failure/fallback behavior, evaluation plan and issue split for implementation
  without adding runtime behavior, persistence/schema, provider config,
  deployment, admin UI or release/privacy claims.
  Status: issue #404 / #204A now has a no-code architecture package at
  `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`;
  issues #405-#411 added local contracts/scanner/profile/role-validator/
  snapshot/selector/signature foundations; issue #412 / #204I adds the
  design-only owner-only diagnostics sidecar package at
  `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md`.
  Issue #413 / #204J adds the bounded DeepSeek Pro spike runner and
  metadata-only report at
  `docs/superpowers/specs/2026-06-12-deepseek-pro-glossary-profile-spike-report.md`.
  Issue #414 / #204K adds a local deterministic chunked glossary-editor
  packetizer in `src/translator_service/glossary_editor_packets.py` with
  compact reference payloads, stable ids/signatures, evidence and token-budget
  caps, degradation/skipped metadata and fixture coverage over the three #413
  TXT samples. Issue #415 / #204L adds local fake-output validators and
  deterministic merge/adjudication in
  `src/translator_service/glossary_editor_chunk_outputs.py`, rejecting invalid
  packet/entry/evidence refs, unsafe/raw output, hard-layer promotion and
  oversized outputs while recording duplicates, conflicts and low-confidence
  semantic claims as findings. Issue #416 / #204M adds a standalone bounded
  chunked DeepSeek Pro glossary-editor spike runner and metadata-only report;
  the approved live run made 3 calls, observed 16973 provider tokens, validated
  only the small sample packet and recorded two invalid larger-fixture outputs
  due to missing evidence refs. Issue #430 / #204N tightens the local
  fake-output prompt/evidence contract so valid fake chunks cite resolvable
  packet evidence refs and missing refs remain structured blocker failures.
  Issue #432 / #204P adds a local metadata-only evaluator so future
  glossary/editor steps must measure schema validity, evidence-ref coverage,
  invalid chunk rate, blocker/warning findings, duplicate/conflict rate,
  prompt budget overrun, `needs_review` rate and provider token-cap evidence
  before provider retry or runtime architecture review. Issue #433 / #204Q
  records the no-code runtime integration boundary, fallback matrix,
  cache/signature caveats, diagnostics boundary and approval gates before any
  runtime glossary/profile integration. Runtime integration remains rejected
  for now; further live provider work and runtime prompt/cache/storage/admin/
  retention implementation require fresh exact owner approval. Issue #431 /
  #204O ran the approved bounded retry after #430; it made 3 calls, observed
  19592 provider tokens, validated only the small sample packet, and recorded
  two invalid larger-fixture outputs due to provider `length` completions and
  invalid JSON. The recommendation remains pivot/iterate before runtime
  integration.

- Task: Owner-only glossary/profile diagnostic sidecar foundation.
  Risk reduced: R-014, R-019, R-020, R-036.
  Priority: High.
  Suggested owner: Implementer / Reviewer / Human.
  Acceptance criteria: dedicated sidecar schema, raw-field manifest, secret
  exclusion, ordinary-surface metadata summaries, tests, and explicit `TBD`
  retention/export/delete policy.
  Decision status: issue #434 / #204R implemented the schema/validator/
  metadata-summary/read-write foundation only. No admin UI, archive inclusion,
  runtime prompt behavior, provider population, storage policy, retention,
  export/delete implementation or release/privacy claim was added.

- Task: Disabled-by-default glossary/profile runtime-shadow and prompt-policy
  adapter planning path.
  Risk reduced: R-014, R-019, R-036.
  Priority: High.
  Suggested owner: Implementer / Reviewer.
  Acceptance criteria: default disabled behavior, compact signatures/selections,
  no live provider calls, no prompt injection, no durable state mutation,
  cache bypass for glossary-injected enabled/test-path units, fallback for
  invalid/over-budget data, tests and docs.
  Decision status: issue #435 / #204S implemented a local helper and tests only.
  Issue #466 / #204AH implements a disabled-by-default prompt-policy adapter
  decision contract that accepts compact shadow metadata in an enabled/test path
  and falls back for unready data. Issue #474 adds a controlled default-off
  runtime hook in the DOCX/EPUB runner that can emit compact adapter metadata
  and request cache bypass for READY enabled/test-path units only. Issue #475 /
  #204AK adds only a local bounded glossary prompt-context formatter with
  escaping, budget caps and metadata-only omission reporting. Issue #476 /
  #204AL adds a disabled/test-only fake runtime rehearsal that prefixes
  DOCX/EPUB fake-provider requests with bounded glossary context only when an
  explicit rehearsal flag is enabled and the adapter decision is READY, with
  compact metadata-only callbacks. Issue #477 / #204AM adds the bounded live
  provider smoke runner/report; fake preflight passed, three approved TXT calls
  validated and the approved EPUB RU/UK calls failed on provider `length` plus
  local `truncated_output`/`external_text` validation. Issue #478 / #204AN
  records a `NEEDS REVIEW` quality verdict because paired non-glossary
  comparison outputs were unavailable, so comparative glossary benefit remains
  `Unknown`. Issue #479 / #204AO records metadata-only decision preparation:
  normal/default and limited-beta runtime glossary rollout were rejected for
  that evidence state, and the final owner path remained `TBD`. Issue #640 now
  records a separate owner-approved #639 default-integration path, but
  glossary-aware cache reuse, database/scheduler/work-unit state, storage/
  admin/retention behavior, deployment and release/privacy claims remain
  unchanged outside that approved path.

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
  no raw text outside approved owner-only diagnostics/downloads, no secrets, no
  public admin, no paid flow before Gate C.
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
