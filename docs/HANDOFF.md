# Handoff

Last updated: 2026-06-02

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
TTL cleanup/delete verification, real-file
TXT/DOCX/EPUB release matrix, local/offline EPUBCheck validation, DOCX
openability/visual QA, Alerts MVP, Backups visibility, restore rehearsal artifact,
cancel/resume/restart release evidence и server smoke evidence.

Что неизвестно: `.github/workflows/checks.yml` существует, но GitHub Actions
run/pass status для отдельной ветки остается Unknown until a PR check exists
and is inspected; public production readiness не подтверждена.

Issue #72 verification update on 2026-05-23: dedicated local Gate B common
verification passed on branch `codex/issue-72-gate-b-baseline`:
`PYTHONPATH=src python3 -m unittest discover -s tests` ran 1046 tests with
`OK (skipped=13)`, `PYTHONPATH=src python3 -m compileall src` passed, and
`scripts/predeploy_check.sh` passed. This is local evidence only; it does not
prove CI, server smoke, real-file matrix, restart, backup/restore or other Gate
B blockers.

Issue #78 redaction update on 2026-05-28: release-wide logs/admin raw-text
redaction evidence passed locally on branch `codex/issue-78-gate-b-redaction`
using synthetic fixtures only. The review found that admin translation-log
archive downloads could include raw run error details; focused bug
[#117](https://github.com/ogirkoviylord/folioloom_main/issues/117) records that
leak risk. The fix redacts translation run artifact event payloads and error
fields before archive generation, and regression tests inspect archive contents
for raw source/translated snippets, prompt text, API-key-like strings, provider
key identifiers and traceback markers. Local verification for #78 passed
focused redaction/admin/security tests, full unittest, compileall, targeted
ruff and `scripts/predeploy_check.sh`. This does not prove real-file matrix,
beta-server smoke, backup/restore or full Gate B readiness.

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
- 2026-05-28: Duplicate upload / retry architecture for issues #120-#125 uses
  a no-schema first implementation: bounded same-user metadata scan with limit
  `100`, no cross-user dedupe, no concurrent fresh `translate again` while a
  duplicate job is active, resume remains My Books-only, and free
  retry/retranslate stays beta-safety accounting rather than paid billing.
  Implementation order is #121 fresh attempt semantics before #123 duplicate
  upload UX. Durable indexed duplicate keys, schema/state changes and
  retention/TTL cleanup require separate owner approval.
- 2026-05-29: Issue #121 implementation slice is locally verified. New pending
  upload/translation attempts carry an internal attempt id that makes repeated
  same-document preview reservation ids distinct while keeping same-pending
  duplicate preview protection. Repeated persistent translations create
  distinct job ids, preserve old and new My Books/history result access, keep
  rights confirmation in the upload flow and continue to reserve/consume beta
  safety separately for each preview/job. This does not implement #123 duplicate
  upload UX, durable duplicate indexes, schema changes, concurrent duplicate
  work, TTL cleanup or paid retry policy. Local verification on branch
  `codex/issue-121-translate-again-fresh-attempt`: focused bot repeat-attempt
  tests passed, `tests.test_bot_translation_service tests.test_bot_runtime`
  passed, `tests.test_persistent_jobs tests.test_postgres_scheduler` passed,
  full `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1122 tests
  with `OK (skipped=13)`, `PYTHONPATH=src python3 -m compileall src` passed,
  and targeted ruff on the changed Python files passed. CI status remains
  Unknown until a PR/checks page is inspected.
- 2026-05-29: Issue #123 implementation slice is locally verified on branch
  `codex/issue-123-duplicate-upload-ux`. The upload flow now performs a
  read-only same-user duplicate lookup after rights confirmation, translation
  mode and target language selection, but before preview/provider work. The
  first slice scans at most `100` same-user persistent jobs by source metadata
  and approved identity fields, skips missing source metadata/object safely,
  shows neutral duplicate choices for ready/active/recoverable matches, does
  not show upload-flow Continue Translation, and keeps resume My Books-only.
  Existing ready results can be downloaded or translated again as a fresh
  attempt; active duplicates do not offer concurrent translate-again. Local
  verification: `tests.test_bot_messages tests.test_bot_runtime
  tests.test_bot_translation_service` ran 249 tests with `OK`,
  `tests.test_persistent_jobs tests.test_postgres_scheduler` ran 40 tests with
  `OK (skipped=13)`, full unittest discover ran 1129 tests with
  `OK (skipped=13)`, compileall over `src` passed, and targeted
  `ruff --select F,I` on changed files passed. This does not add durable
  duplicate indexes, schema changes,
  concurrent duplicate work, upload-flow resume, TTL cleanup, paid retries,
  deployment, release readiness or CI evidence.
- 2026-05-30: Issue #125 implementation slice is locally verified on branch
  `codex/issue-125-my-books-resume-controls`. My Books detail now shows
  `Continue Translation` only when the job status is architecture-approved as
  recoverable and the stored source object is still available for backend
  resume. Duplicate-upload choices still never show `Continue Translation`;
  partial duplicate results now provide both partial download and an explicit
  open-existing/My Books path for recovery. Partial-result user copy is neutral
  and does not describe skipped passages as quality problems. Local
  verification: `PYTHONPATH=src python3 -m unittest tests.test_bot_messages
  tests.test_bot_runtime tests.test_bot_translation_service` ran 253 tests with
  `OK`; full `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1133
  tests with `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src`
  passed; targeted `python3 -m ruff check --select F,I` on changed files
  passed. This does not change durable job/work-unit semantics, add
  schema/state changes, perform runtime data operations, implement upload-flow
  resume, or close broad Gate B cancel/resume/restart evidence in #81. CI
  status remains Unknown until a PR/checks page is inspected.
- 2026-05-30: Issue #134 implementation slice is locally verified on branches
  `codex/issue-134-investigate` and `codex/issue-134-file-fallback`. Upload
  Safety admin now builds a metadata-only accepted/blocked/failed-closed read
  model from deduplicated `security.upload_safety.summary` activity snapshots,
  including sanitized filename and job correlation when available. If an
  older/correlation upload safety activity has `job_id` but lacks filename
  metadata, the admin view can fall back to the matching user's persistent job
  `file_name` through a read-only lookup, sanitizing it without exposing object
  storage keys. Clean accepted uploads through the required scanner gate remain
  visible as `accepted`/`clean`; persistent jobs keep the worker-facing
  `translation_policy.upload_safety` marker; run artifacts also include a safe
  upload-safety marker without object storage keys. Local verification used
  synthetic fixtures only and did not inspect
  real `.env*`, live beta/server runtime data, `var/` data or user documents:
  focused upload-safety/admin tests passed, `tests.test_admin_upload_safety`
  and `tests.test_bot_translation_service` passed, full unittest discover ran
  1140 tests with `OK (skipped=13)`, compileall passed, targeted ruff passed,
  `scripts/predeploy_check.sh` passed, and visible GitHub `Python checks` for
  PR #136 passed. This does not implement TTL cleanup, deployment/server smoke,
  production readiness, public/external scanning, scanner override/rescan
  controls or any live runtime-data repair.
- 2026-05-30: Issue
  [#137](https://github.com/ogirkoviylord/folioloom_main/issues/137)
  implementation slice is locally verified on branch
  `codex/new-upload-failure`. New persistent TXT/DOCX/EPUB job beta-safety
  reservations now use the adapter plan's `estimated_input_tokens` instead of
  the previous `fragment_count * max_fragment_chars` capacity estimate. This
  keeps beta caps unchanged while avoiding false `job_estimate_cap` rejections
  for EPUB files with many small work units. Regression coverage uses synthetic
  EPUB content only and confirms a >1000-work-unit EPUB whose planned estimate
  is within the default job cap queues successfully, while the old capacity
  estimate would have exceeded the cap. Local verification: focused red/green
  tests for persistent reservation and EPUB cap behavior passed;
  metadata-only local estimate checks of owner-provided `pg45304-images-3.epub`
  and `pg2641-images-3.epub` printed no raw book text and showed
  `pg45304-images-3.epub` planned beta-safety cost `0.639347` vs old capacity
  cost `3.04842`, and `pg2641-images-3.epub` planned cost `0.144057` vs old
  capacity cost `0.28428`;
  `PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service` ran
  111 tests with `OK`; `PYTHONPATH=src python3 -m unittest
  tests.test_bot_runtime tests.test_persistent_jobs
  tests.test_persistent_job_store` ran 112 tests with `OK`; full
  `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1141 tests with
  `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src` passed;
  targeted `python3 -m ruff check --select F,I` on changed Python files passed;
  `git diff --check` passed. CI status remains Unknown until a PR/checks page
  is inspected. This does not change beta limits/pricing rates, persistent DB
  schema/state, runtime `var/` data, deployment, secrets, legal/privacy policy,
  or release readiness.
- 2026-05-30: Issue
  [#139](https://github.com/ogirkoviylord/folioloom_main/issues/139)
  implementation slice is locally verified on branch
  `codex/worker-failure-beta-release`. Owner-provided `pg2641-images-3.epub`
  run-log export showed a deferred worker job that reached `run_failed` with
  `0` prompt/completion tokens and no work-unit progress, meaning the failure
  happened before successful translation usage was recorded. The scheduler now
  releases the job's beta-safety reservation when it observes a terminal
  deferred worker failure and keeps retryable worker failures running/reserved.
  Regression coverage confirms the terminal failure path writes the existing
  safe generic run-log error without raw source/provider details and releases
  the reservation with reason `terminal_failure`; the retryable failure path
  keeps the run log running and does not release/consume the reservation. Local
  verification: focused red/green scheduler tests passed; `PYTHONPATH=src
  python3 -m unittest tests.test_scheduler_runner` ran 25 tests with `OK`;
  `PYTHONPATH=src python3 -m unittest tests.test_worker tests.test_beta_safety
  tests.test_beta_safety_store tests.test_scheduler_runner` ran 89 tests with
  `OK`; full `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1141
  tests with `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src`
  passed; targeted `python3 -m ruff check --select F,I` on changed Python files
  passed; `git diff --check` passed. CI status remains Unknown until a
  PR/checks page is inspected. This does not repair existing active
  reservations in live runtime data, change beta limits/pricing/provider
  behavior, alter schema/state, perform deployment/server operations, read real
  `.env*`, or claim release readiness.
- 2026-05-31: Issue
  [#161](https://github.com/ogirkoviylord/folioloom_main/issues/161)
  implementation slice is locally verified on branch
  `codex/issue-161-scheduled-progress-mismatch`. Admin translation logs,
  translation details, trace and user support translation summaries now overlay
  active scheduled-job progress from the read-only operations/work-unit view
  when the run artifact still shows stale `0/N` fragments and `0` tokens.
  The run artifacts remain unchanged; the admin read model reports metadata-only
  counts, progress percent, token totals, timestamps, status and safe error
  excerpt from scheduler state. Local verification: focused admin routes/live/
  logs/trace/operations/action-center tests passed, full unittest discover ran
  1161 tests with `OK (skipped=13)`, compileall passed, and targeted
  `ruff --select F,I` on changed Python files passed. CI status remains Unknown
  until a PR/checks page is inspected. This does not perform live runtime-data
  repair, mutate scheduler/job/work-unit state, change schema, deploy or
  restart server services, change provider behavior, read real `.env*`, or
  claim release readiness.
- 2026-05-31: Issue
  [#164](https://github.com/ogirkoviylord/folioloom_main/issues/164)
  implementation slice is locally verified on branch
  `codex/issue-164-my-books-progress`. My Books book detail now shows
  metadata-only translation progress for active/recoverable persistent jobs
  when work-unit counts are available, using completed/total fragments and a
  percentage without raw source text, translated text, prompts or provider
  internals. Owner expanded the scope in chat on 2026-05-31 to add compact
  status indicators to My Books inline buttons: ready books show a check mark,
  active jobs show a gear, and recoverable incomplete jobs show a resume-style
  marker. Local verification: `tests.test_bot_messages` ran 62 tests with
  `OK`; `tests.test_bot_runtime tests.test_bot_translation_service` ran 197
  tests with `OK`; full unittest discover ran 1167 tests with
  `OK (skipped=13)`; compileall over `src` passed; targeted
  `ruff --select F,I` on changed Python files passed; `git diff --check`
  passed. CI status remains Unknown until a PR/checks page is inspected. This
  does not change scheduler/job/work-unit persistence semantics, schema,
  runtime data, provider behavior, beta caps, deployment, payments, auth/RBAC,
  legal/privacy copy, upload-flow resume, duplicate-upload behavior or release
  readiness.
- 2026-06-01: Issue
  [#174](https://github.com/ogirkoviylord/folioloom_main/issues/174)
  implementation slice is locally verified on branch
  `codex/174-same-language-guard`. The upload/preview path now blocks
  accidental same-language translation attempts when `source_language=auto`
  resolves to the same base language as the selected target, including detected
  displays with admixtures such as `Russian (admixtures: English, Polish)`.
  The bot keeps the upload in language-selection state, shows neutral user copy
  to choose a different target language or cancel, and does not start preview,
  provider work, full translation or beta-safety reservation/consumption for
  the blocked attempt. Local verification: focused new RED/GREEN tests passed;
  `PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service
  tests.test_bot_runtime tests.test_bot_messages` ran 264 tests with `OK`;
  full `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1177 tests
  with `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src` passed;
  targeted `ruff --select F,I` on changed Python files passed; `git diff
  --check` passed. CI status remains Unknown until a PR/checks page is
  inspected. This does not add same-language rewrite/polish mode, change
  provider prompts, repair existing failed jobs, change scanner/upload
  enforcement, mutate scheduler/database/runtime state, change payments,
  deployment, auth/RBAC, legal/privacy copy or claim release readiness.
- 2026-06-01: Issue
  [#175](https://github.com/ogirkoviylord/folioloom_main/issues/175)
  implementation slice is locally verified on branch
  `codex/issue-175-epub-unexpected-xml-attributes`. The provider batch-output
  path now uses a narrow provider-only normalization step for otherwise valid
  `translation_batch` XML that adds harmless language metadata attributes
  `target_language`, `lang` or `xml:lang` on the allowed root/block tags. The
  strict validator remains strict by default; normalized provider output strips
  those metadata attributes before return/storage, preserves required block ids
  and existing `source_language` hints, and still rejects control/unknown
  attributes such as `role` or `override`, unexpected elements, malformed XML,
  wrong ids/counts, external text, unsafe output/tool claims and missing
  protected markers. A metadata-only `translation_batch_normalized` security
  event records the normalization without raw source text, translations, prompts
  or provider internals. Local verification: focused output-contract,
  DeepSeek-client and prompt-security regression tests ran 38 tests with `OK`;
  full `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1182 tests
  with `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src` passed;
  targeted `ruff --select F,I` on changed Python files passed; `git diff
  --check` passed. CI status remains Unknown until a PR/checks page is
  inspected. This does not repair the existing failed EPUB job, change
  scheduler/worker retry semantics, mutate database/runtime state, deploy or
  restart services, change provider keys/prompts, expand EPUB book-mode scope,
  alter payments/auth/legal/privacy/deployment, or claim Gate B/release
  readiness.
- 2026-06-02: Issue
  [#166](https://github.com/ogirkoviylord/folioloom_main/issues/166)
  implementation slice is locally verified on branch
  `codex/166-book-mode-output-audit`. A new pure
  `book_mode_output_audit` module adds deterministic, non-blocking
  book-mode output audit primitives for Russian/Ukrainian targets. Findings are
  structured metadata only: code, category, target language, chunk id/kind,
  language counts, protected-marker count and safe language-metadata details.
  The checks detect obvious English residue, English navigation/heading
  residue, provider commentary wrappers, suspicious all-English chunks and
  language metadata mismatch while masking URLs, code-like spans, identifiers,
  protected markers and caller-provided expected Latin terms. Local
  verification: focused book-mode/Russian/Ukrainian quality tests ran 28 tests
  with `OK`; full `PYTHONPATH=src python3 -m unittest discover -s tests` ran
  1223 tests with `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src`
  passed; targeted `python3 -m ruff check` on changed Python files passed; new
  file whitespace checks passed. CI status remains Unknown until a PR/checks
  page is inspected. This does not wire audit checks into runtime, block
  translation jobs, trigger provider retries, change admin UI, use real
  documents or runtime `var/` data, add dependencies, change legal/privacy,
  auth/RBAC, payments, deployment, database/state or claim release readiness.
- 2026-06-01: Owner approved permanent, owner-only raw translation text
  diagnostics after a failed EPUB translation showed that safe exports did not
  contain enough information to compare source work units, translated output and
  retry/error state. PR #179 added a metadata-only work-unit snapshot to normal
  translation details, plus a dedicated SSH-tunneled admin-session page for
  stored source/translated work-unit text; after merge/deploy the owner accepted
  this first interface as the ongoing direction. The normal details page and
  downloadable diagnostics remain metadata-only/redacted. Local verification for
  this slice is recorded in the task response. This does not expose raw text
  through safe archives/telemetry/JSON APIs, authorize copying excerpts to
  issues/PRs/support notes, relax public admin restrictions or change Gate B
  release requirements.
- 2026-06-02: Owner additionally approved viewing raw provider prompt bodies in
  a dedicated owner-only diagnostic surface. This is a decision-level approval,
  not evidence that prompt bodies are already stored or rendered. Implementers
  should use a separate scoped issue for prompt diagnostics and keep normal
  trace/evidence/archive/telemetry/API surfaces metadata-only/redacted.
- 2026-06-01: During the follow-up live EPUB translation, backend/admin state
  showed the job still translating and progressing past the previously failed
  work unit, while the Telegram message could remain stuck on the queued copy.
  Root cause in local code: the direct worker-progress polling edit path did
  not tolerate Telegram's harmless `message is not modified` response, so a
  repeated queued edit could abort polling before later progress edits. Local
  fix makes only that progress polling edit treat this exact response as a
  no-op and continue watching the job. Focused `tests.test_bot_runtime`
  verification passed. This does not deploy/restart services or change worker,
  scheduler, provider, auth, raw-text access or runtime data.
- 2026-05-30: Umbrella issue
  [#120](https://github.com/ogirkoviylord/folioloom_main/issues/120)
  is closed after the planned first-slice work was completed and merged.
  Child issues #122, #124, #121, #123 and #125 are closed; PRs #126-#130 are
  merged into `main`, and visible GitHub `Python checks` passed for each PR.
  The closed scope covers the narrow repeated-preview bugfix, approved
  duplicate/retry architecture, fresh translate-again attempts, same-user
  duplicate upload UX and My Books-only resume controls. This does not close
  durable indexed duplicate keys, schema/state changes, concurrent duplicate
  work, upload-flow resume, TTL/delete cleanup, paid retry policy, deployment,
  release readiness or broad Gate B cancel/resume/restart evidence.
- 2026-05-31: Owner approved the admin redesign direction as a before-free
  closed beta Beta Operations Console effort. The accepted direction is
  incident-first and read-only by default: Translation Failure Trace and safe
  evidence packet first, then provider/key incident clarity, overview triage,
  navigation cleanup, action semantics and user support/debug views. The design
  is recorded in
  `docs/superpowers/specs/2026-05-31-beta-operations-console-redesign.md`.
  The first admin redesign stack was implemented and merged into `main` by PR
  #160, covering #145-#151; on 2026-06-02 the owner approved closing #145-#152
  as implemented by PR #160. This does not satisfy Gate B, change
  SSH-tunnel-only admin, authorize public admin, payment, deployment,
  auth/RBAC, database/state or user-data changes.
- 2026-06-01: Owner approved the internal/dev before-after reader direction for
  the first slice only. The accepted scope is a local QA reader/report over
  existing TXT/DOCX/EPUB adapter blocks for synthetic fixtures, repository test
  samples, public-domain/permissive authorized fixtures and explicitly
  owner-approved local files. User-facing reader and publisher/editor workspace
  are future work. The design is recorded in
  `docs/superpowers/specs/2026-06-01-internal-before-after-reader-design.md`.
  GitHub issues
  [#181](https://github.com/ogirkoviylord/folioloom_main/issues/181)-[#197](https://github.com/ogirkoviylord/folioloom_main/issues/197)
  split the first implementation, renderer spikes, EPUB local report and EPUB
  XHTML preview/resource slices, the DOCX structure preview slice and the
  format auto-detection CLI slice.
  This does not authorize live runtime `var/` reads, add admin/public routes,
  add production dependencies, change legal/privacy policy or claim release
  readiness.
- 2026-06-01: Issue
  [#181](https://github.com/ogirkoviylord/folioloom_main/issues/181)
  implementation slice is locally verified on branch
  `codex/issue-181-internal-reader-txt-report`. The branch adds a reusable
  internal reader model and HTML renderer, plus an explicit-input local CLI for
  TXT reports. It refuses repo-local runtime `var/` source/mapping/output paths,
  accepts optional JSON block translation mappings, preserves adapter block
  order and metadata, marks missing/done statuses, and HTML-escapes rendered
  source text, translations and metadata. Local verification passed focused
  internal-reader tests, TXT/format-adapter tests, compileall, targeted ruff and
  a CLI smoke on `test_samples/sample_book.en.txt` writing to a temporary
  directory. This does not implement DOCX/EPUB generic reader support, renderer
  spikes, admin/public UI, live translation streaming, production dependency,
  live runtime data access or release readiness.
- 2026-06-01: Issue
  [#182](https://github.com/ogirkoviylord/folioloom_main/issues/182)
  implementation slice is locally verified on branch
  `codex/issue-182-generic-reader-block-model`, stacked on the #181 branch. The
  branch extends `build_reader_document()` so arbitrary `FormatAdapterPlan`
  values can produce semantic reader sections, grouping contiguous blocks by
  `file_name` metadata without reordering the adapter plan. Focused tests cover
  synthetic DOCX and EPUB plans, including stable block ids, kind, group id,
  metadata, EPUB file names, body/auxiliary role metadata and done/missing
  status behavior. Local verification passed focused internal-reader tests,
  format-adapter tests, compileall and targeted ruff. This does not implement
  DOCX visual rendering, EPUB book-like rendering, admin/public UI, live
  runtime data access, production dependency or release readiness.
- 2026-06-01: Issue
  [#183](https://github.com/ogirkoviylord/folioloom_main/issues/183)
  DOCX renderer spike recommendation is recorded in
  `docs/superpowers/specs/2026-06-01-docx-internal-preview-renderer-spike.md`
  on branch `codex/issue-183-docx-renderer-spike`. Recommendation: keep DOCX
  on the semantic/block reader for now, use local LibreOffice Writer/headless
  conversion only as a reference/QA path on approved fixtures, and do not add
  `docx-preview`, Mammoth or LibreOffice automation as a production dependency
  without a separate owner-approved prototype/implementation issue. This does
  not implement DOCX visual rendering, add a dependency, change deployment,
  add admin/public UI, read live runtime data or claim DOCX fidelity/release
  readiness.
- 2026-06-01: Issue
  [#184](https://github.com/ogirkoviylord/folioloom_main/issues/184)
  EPUB renderer spike recommendation is recorded in
  `docs/superpowers/specs/2026-06-01-epub-internal-reader-rendering-spike.md`
  on branch `codex/issue-184-epub-renderer-spike`. Recommendation: keep EPUB
  on the semantic/block reader for now, consider a generated
  XHTML/spine/chapter local report before any book-like reader dependency, and
  keep EPUBCheck as validation/reference only. This does not implement EPUB
  book-like rendering, add a dependency, change deployment, add admin/public UI,
  read live runtime data or claim EPUB Gate B validation/release readiness.
- 2026-06-01: Issue
  [#189](https://github.com/ogirkoviylord/folioloom_main/issues/189)
  implementation slice is locally verified on branch
  `codex/issue-189-epub-reader-report`, stacked on the #184 branch. The branch
  adds `build_epub_reader_document()` and `--format epub` support to the
  explicit-input internal reader CLI. The EPUB report uses the existing adapter
  plan, preserves spine/file order exposed by the adapter, keeps body and
  auxiliary metadata in the side-by-side HTML report, marks done/missing block
  translations and rejects repo-local runtime `var/` source paths. Local
  verification passed focused internal-reader tests, format-adapter tests,
  compileall, targeted ruff, `git diff --check` and an EPUB CLI smoke writing
  to a temporary directory. This does not implement book-like EPUB rendering,
  add `epub.js`/Readium, run EPUBCheck, add admin/public UI, read live runtime
  data or claim release readiness.
- 2026-06-01: Issue
  [#191](https://github.com/ogirkoviylord/folioloom_main/issues/191)
  implementation slice is locally verified on branch
  `codex/issue-191-epub-xhtml-preview`, stacked on the #189 branch. The branch
  adds sandboxed EPUB XHTML chapter preview panes to the existing explicit-input
  EPUB reader report. Source and adapter-assembled translated XHTML/HTML files
  are shown side by side in `iframe srcdoc` panes with no script permissions,
  while the semantic block report remains below for stable ids, metadata and
  done/missing statuses. Local verification passed focused internal-reader
  tests, format-adapter tests, compileall, targeted ruff, `git diff --check`
  and an EPUB CLI smoke writing to a temporary directory. This does not add
  `epub.js`/Readium, bundle EPUB CSS/images/resources, run EPUBCheck, add
  admin/public UI, read live runtime data, claim full book-like fidelity or
  claim release readiness.
- 2026-06-01: Issue
  [#193](https://github.com/ogirkoviylord/folioloom_main/issues/193)
  implementation slice is locally verified on branch
  `codex/issue-193-epub-preview-resources`, stacked on the #191 branch. The
  branch inlines local linked CSS and safe raster images (`png`, `jpg`, `jpeg`,
  `gif`, `webp`) into the sandboxed EPUB XHTML preview panes, using data URIs
  and a restrictive `srcdoc` Content Security Policy. Missing resources remain
  non-fatal, unsupported/risky resources such as SVG are not embedded, and the
  semantic block report remains below the preview. Local verification passed
  focused internal-reader tests, format-adapter tests, compileall, targeted
  ruff, `git diff --check` and an EPUB CLI smoke writing to a temporary
  directory. This does not add `epub.js`/Readium, fetch remote resources,
  embed fonts/media overlays, run EPUBCheck, add admin/public UI, read live
  runtime data, claim full book-like fidelity or claim release readiness.
- 2026-06-01: Issue
  [#195](https://github.com/ogirkoviylord/folioloom_main/issues/195)
  implementation slice is locally verified on branch
  `codex/issue-195-docx-structure-preview`, stacked on the #193 branch. The
  branch adds `build_docx_reader_document()`, `render_docx_reader_html()` and
  `--format docx` support to the explicit-input internal reader CLI. The DOCX
  report renders a semantic structure preview before the block report, with
  heading/plain/list blocks shown as document flow and table/list groups
  grouped from existing adapter `group_id` metadata. The block report remains
  below the preview with stable ids, kind, group id, metadata and done/missing
  statuses. Local verification passed focused internal-reader tests,
  format-adapter tests, compileall, targeted ruff and a DOCX CLI smoke writing
  to a temporary directory. This does not claim full DOCX/Word visual fidelity,
  add `docx-preview`/Mammoth/LibreOffice automation, add admin/public UI, read
  live runtime data, change legal/privacy policy or claim release readiness.
- 2026-06-01: Issue
  [#197](https://github.com/ogirkoviylord/folioloom_main/issues/197)
  implementation slice is locally verified on branch
  `codex/issue-197-reader-format-auto`, stacked on the #196 branch. The
  explicit-input internal reader CLI now defaults to format auto-detection by
  `.txt`, `.docx` or `.epub` extension, case-insensitively. Explicit
  `--format txt`, `--format docx` and `--format epub` still override extension
  detection, and unknown extensions fail with a clear error asking for an
  explicit supported format. Local verification passed focused internal-reader
  tests, compileall, targeted ruff, `py_compile` for the CLI and CLI smokes
  generating TXT, DOCX and EPUB reports without `--format` into a temporary
  directory. This does not add content sniffing, admin/public UI, live runtime
  data access, dependencies, renderer fidelity changes or release readiness.
- 2026-06-02: Owner approved issue
  [#199](https://github.com/ogirkoviylord/folioloom_main/issues/199)
  for a narrow owner-only Internal Reader admin UI. The scope is an authenticated
  internal form and preview route for approved local TXT/DOCX/EPUB files plus an
  optional JSON block translation mapping, reusing
  `src/translator_service/internal_reader.py`. This authorizes only the focused
  owner-only UI slice; it does not authorize public routes, Telegram/user-facing
  reader, publisher/editor workspace, live runtime `var/` browsing, auth/RBAC
  changes, production dependencies, legal/privacy copy changes, full
  DOCX/EPUB fidelity claims or release readiness.
- 2026-06-02: Branch `codex/internal-reader-v2` adds a run-log Translation
  Reader at `/admin/logs/{run_id}/reader`. It is linked from logs, translation
  details and Text diagnostics, uses the same `run_id -> job_id` work-unit path
  as Text diagnostics, renders owner-only `no-store` HTML with synchronized
  Original/Translation panes, and keeps details/API/download archives
  metadata-only/redacted. Local verification passed `tests.test_admin_routes`,
  focused reader/diagnostics tests, targeted ruff for touched Python files and
  `PYTHONPATH=src python3 -m compileall src`. This does not add public routes,
  raw-text JSON APIs, archive raw text, arbitrary server-path browsing, runtime
  `var/` browsing, auth/RBAC changes, dependencies, publisher workspace or
  release readiness.
- 2026-06-02: Issue
  [#214](https://github.com/ogirkoviylord/folioloom_main/issues/214) starts the
  first focused controls slice for the run-log Reader/Text Diagnostics UX on
  branch `codex/issue-214-reader-controls`, stacked after the scroll-fix PR.
  The slice adds opt-in invisible/special-character markers, logical
  sequence-window Previous/Next navigation, jump-by-sequence controls and a
  reader sync-scroll toggle while keeping raw text confined to the same
  owner-only `no-store` surfaces. Local verification passed
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, focused
  regression coverage for the new controls, targeted ruff for touched Python
  files and `PYTHONPATH=src python3 -m compileall src`. Physical book pages,
  format-aware chapter navigation, search, anomaly filters, minimap,
  publisher/editor workspace, live runtime data access and full DOCX/EPUB
  fidelity remain out of scope.

AI-agent workflow update on 2026-05-23: `AGENTS.md` now defines a compact Skill
Dispatch Contract, and `docs/AGENT_SKILL_ROUTING.md` is the detailed reference
for selecting repo-level roles, supporting skills, approval evidence, stop-list
behavior and routing receipts. Future agents should prefer repo-level
`.agents/skills/*` over global skills with similar names and use the
highest-risk route when classifications overlap. Owner-facing responses should
be Russian by default unless the owner asks otherwise.

## 2. Текущий фокус

Текущий рабочий фокус по репозиторию: prepare free closed beta by stabilizing
core flow, release gates, operational visibility and documentation.

Подтвержденные подпункты фокуса:

- закрыть Gate B blockers для free closed beta;
- улучшить upload safety, TTL/delete verification и real-file QA;
- поддерживать local malware/AV scanning gate как часть upload safety; owner
  accepted this direction on 2026-05-22 and selected local ClamAV `clamd`
  daemon/socket with `INSTREAM` scanning as the target adapter mode on
  2026-05-26. Issue #93 added the code/tests-only adapter slice. Issue #109
  added the internal-only Docker Compose/runtime `clamd` service, env-driven
  scanner config, bounded scan concurrency/backpressure and metadata-only
  runtime health/version plus EICAR smoke check. On 2026-05-27, an isolated
  local compose smoke for #109 passed with `clamd` reachable on the internal
  Docker network, `status=ok`, `scanner_version=ClamAV 1.4.4`,
  `signature_database_version=28010` and `eicar_verdict=infected`; real
  `.env*`, `var/` and user data were not used. Issue #95 metadata-only local
  evidence on 2026-05-27 passed focused scanner/upload/runtime/deployment
  tests, full unittest, compileall and predeploy, and marks the Gate B
  malware/AV scanning item checked in the evidence report. Issue #73 now marks
  the upload hardening/quarantine baseline checked for local synthetic evidence.
  This does not close TTL cleanup, approved beta-server smoke or full Gate B
  readiness;
- GitHub issue [#173](https://github.com/ogirkoviylord/folioloom_main/issues/173)
  is approved for a focused implementation slice as of 2026-06-01. Owner
  approved fail-closed beta upload scanning, Docker/env scanner config updates,
  focused tests and docs, while forbidding real `.env*` access, live runtime
  data operations and server smoke without separate exact approval. The slice
  restores production-like runtime scanner defaults to local/internal `clamd`
  when scanner env is absent and raises the documented beta `clamd` memory
  default above the OOM-prone `1g` limit. Owner-approved metadata-only 173D
  server smoke on 2026-06-01 found the current beta runtime still mismatched:
  `folioloom-clamd-1` was `unhealthy`, app settings inside the running bot
  container reported scanner enforcement disabled with backend `none` and
  `clamd_host=127.0.0.1`, scanner env names were absent, and the internal
  `clamd` EICAR check failed with `clamd is unavailable`. No real `.env*`,
  runtime files, object keys, user files or raw document text were read or
  printed. Target-host adequacy for the new `2g` default remains Unknown until
  the fixed config is deployed and re-smoked with owner approval;
- подтвердить scheduler/runtime consistency, restart/cancel/resume behavior и
  backup/restore readiness;
- treat the first Beta Operations Console/admin redesign stack as implemented
  by PR #160 and issues #145-#152 as closed; handle prompt diagnostics,
  Alerts/Backups visibility and release evidence as separate follow-ups;
- prepare the owner-approved internal/dev before-after reader in scoped issues,
  continuing after the locally verified #181 TXT report slice with #182 generic
  DOCX/EPUB block model and #183/#184 renderer spikes;
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
  `worker.py` so scheduled terminal worker failures finish matching running
  translation run logs as `failed` with a generic safe error message. Retryable
  scheduled worker failures keep the run log `running` while the persistent job
  remains `translating` and waits for retry. Local verification reported on
  2026-05-13: focused scheduler/worker tests, worker/scheduler suites,
  `PYTHONPATH=src python3 -m compileall src`,
  `PYTHONPATH=src python3 -m unittest discover -s tests` with 984 tests OK and
  13 skipped, and `git diff --check`. Follow-up local verification for the
  retryable-vs-terminal run-log behavior on 2026-05-28: targeted
  scheduler/worker/bot-runtime tests passed, `PYTHONPATH=src python3 -m compileall src`
  passed, and `PYTHONPATH=src python3 -m unittest discover -s tests` passed
  1117 tests with 13 skipped. GitHub Actions status is Unknown until PR checks
  are inspected.
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
- Current behavior: Policy exists; release gate is now checked for the local
  synthetic baseline from issue #73. Code has upload validation, document
  content/container validation, document sandbox modules, an optional pluggable scanner
  contract with fake scanner tests from issue #92, and issue #94 wiring that
  uses the Upload Safety Ledger when `require_upload_scan` is enabled:
  quarantine first, clean ledger-backed accepted source before parser/estimate/
  preview/persistent-job access, fail-closed persistent resume when the current
  ledger cannot resolve the accepted source, and stored-worker rejection for
  quarantine, explicitly unaccepted source object keys, or scan-gated detached
  worker jobs that lack a safe `translation_policy.upload_safety` accepted-source
  marker. Issue #103 adds a read-only admin Upload Safety surface backed by
  metadata-only `security.upload_safety.summary` activity events that are shared
  through the existing admin activity DB between the bot and API processes:
  overview/list/detail pages, safe filters, timeline rendering and redaction
  coverage for full hashes, object keys, quarantine paths, raw scanner output,
  raw exception details and raw document text. `REQUIRE_UPLOAD_SCAN=true` with
  `UPLOAD_SCANNER_BACKEND=clamd` enables the runtime scan gate. Issue #93 adds
  the local `clamd` `INSTREAM` adapter, and issue #109 adds an internal-only
  `clamd` Docker Compose service plus metadata-only PING/VERSION and EICAR
  smoke check. Issue #73 adds stdlib-only TXT/DOCX/EPUB validation before
  accepted source creation and local synthetic evidence for unsupported
  extensions, wrong extension/content mismatch, invalid/binary TXT, corrupt ZIP,
  traversal/absolute paths, archive size/count/compression limits, missing
  expected structure and executable-looking embedded paths. Clean-scanned unsafe
  containers fail closed from quarantine without parser/sandbox calls, accepted
  original source objects, pending uploads or persistent jobs/work units, and
  upload-safety activity remains metadata-only. Local isolated #109 smoke on
  2026-05-27 confirmed
  `status=ok`, `scanner_version=ClamAV 1.4.4`,
  `signature_database_version=28010` and `eicar_verdict=infected` from an app
  image container without real `.env*`, `var/` or user data. Release docs still
  do not claim quarantine retention, durable raw upload-safety ledger
  persistence, approved server smoke evidence or full Gate B readiness. Owner
  accepted adding a local malware/AV scanning gate on
  2026-05-22, and issue #95 now records scoped metadata-only Gate B malware/AV
  scanning evidence.
- Evidence: `docs/restart/upload-safety-and-retention.md`,
  `docs/restart/release-gates.md`, `src/translator_service/documents.py`,
  `src/translator_service/document_sandbox.py`,
  `src/translator_service/document_scanner.py`,
  `src/translator_service/upload_safety_ledger.py`,
  `src/translator_service/admin/upload_safety.py`,
  `src/translator_service/admin/routes.py`,
  `src/translator_service/admin/views.py`,
  `tests/test_documents.py`, `tests/test_bot_translation_service.py`,
  `tests/test_admin_upload_safety.py`.
- Risk: real-file parser/adapter QA, TTL/quarantine cleanup and approved
  beta-server smoke remain separate Gate B blockers; public external scanning
  could leak rights-sensitive documents if used as the default.
- Suggested next task: verify TTL/quarantine cleanup evidence and real-file
  TXT/DOCX/EPUB matrix. Any deployment, external scanning, retention,
  live/beta server operation or runtime-data behavior still needs explicit
  owner approval.

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

- Problem: TTL cleanup/delete policy is documented but not gate-checked.
- Evidence: `docs/restart/upload-safety-and-retention.md` and unchecked Gate B
  TTL cleanup item.
- Impact: retention and delete expectations may be unproven.
- Suggested fix task: implement cleanup/delete verification with human approval
  where user-data handling, runtime data or live/beta environments are involved.

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

- Задача: keep upload hardening/quarantine baseline in regression checks.
  Почему важно: unsafe files must not reach workers.
  Риск: parser, storage and raw-text leakage risk.
  Кто должен делать: Reviewer.
  Можно ли отдавать агенту: yes for local synthetic regression checks; needs
  approval if behavior changes user data handling or quarantine retention.
  Status note: issue #73 records local synthetic evidence and checks this Gate B
  item only; TTL/quarantine cleanup, real-file QA, approved beta-server smoke
  and full Gate B readiness remain separate blockers.

- Задача: maintain local malware/AV scanning gate evidence in release checks.
  Почему важно: untrusted uploads must be scanned before parsing without sending
  private books/manuscripts to public scanning services by default.
  Риск: security, privacy, deployment, dependency and runtime user-data risk.
  Кто должен делать: Architect / Implementer / Reviewer.
  Можно ли отдавать агенту: yes for metadata-only local/synthetic verification;
  deployment/new dependency, external scanning, live/beta server operation,
  retention or runtime-data behavior needs explicit owner approval.
  Issues: [#91](https://github.com/ogirkoviylord/folioloom_main/issues/91)
  design, [#92](https://github.com/ogirkoviylord/folioloom_main/issues/92)
  scanner contract, [#101](https://github.com/ogirkoviylord/folioloom_main/issues/101)
  Upload Safety Ledger reconciliation, [#93](https://github.com/ogirkoviylord/folioloom_main/issues/93)
  ClamAV adapter, [#94](https://github.com/ogirkoviylord/folioloom_main/issues/94)
  upload-flow wiring, [#95](https://github.com/ogirkoviylord/folioloom_main/issues/95)
  Gate B evidence.
  Status note: #93, #94, #101, #102, #103 and #109 are closed. #95 records
  metadata-only Gate B malware/AV scanning evidence. #73 records local
  synthetic upload hardening/quarantine evidence. This does not implement or
  approve TTL cleanup, approved beta-server smoke or full Gate B readiness.

- Задача: run release-scoped verification before any go/no-go.
  Почему важно: issue #56 recorded current preview-slice tests, but Gate B still
  needs release evidence for server smoke, real files, restore/backups and
  restart scenarios.
  Риск: preview evidence could be mistaken for full beta readiness.
  Кто должен делать: Reviewer.
  Можно ли отдавать агенту: yes.
  Status: issue #72 recorded the dedicated local common verification baseline on
  2026-05-23; server smoke, real files, restore/backups and restart scenarios
  remain separate Gate B blockers.

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

- Date: 2026-05-23.
- Change: Recorded dedicated local Gate B common verification baseline for issue
  #72.
- Evidence: `docs/restart/gate-b-evidence-report.md` records full unittest
  `Ran 1046 tests`, `OK (skipped=13)`, compileall passed, and
  `scripts/predeploy_check.sh` passed. `docs/restart/release-gates.md` now
  marks only the Gate B common verification item as checked. CI status remains
  Unknown because no PR/check evidence was inspected.
- Follow-up: collect remaining Gate B blocker evidence, especially server smoke,
  real-file matrix, restart/cancel/resume, upload/TTL, backup/restore and
  redaction evidence.

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
