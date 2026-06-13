# Handoff

Last updated: 2026-06-13

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
TTL cleanup/delete verification, provider-backed Telegram real-file
TXT/DOCX/EPUB release matrix, full manual DOCX visual QA, Alerts MVP, Backups
visibility, restore rehearsal artifact, cancel/resume/restart release evidence
и server smoke evidence.

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

Issue #75 local real-file evidence slice on 2026-06-04: branch
`codex/issue-75-real-file-matrix` ran a metadata-only, temp-only, no-provider
adapter/persistent-plan pass for 7 public-domain/permissive fixtures found from
popular internet sources. The pass covered TXT Dracula small, TXT War and Peace
long slice, TXT Cyrillic Detstvo slice, DOCX simple Kobzar, DOCX structured
Dracula, EPUB Kobzar and EPUB Dracula. Upload/content validation, persistent
job/work-unit planning and synthetic final assembly passed for all fixtures.
DOCX outputs passed local LibreOffice headless PDF conversion with no repair
marker in CLI output, and EPUB outputs passed EPUBCheck v5.3.0 with `0` fatals,
errors or warnings using a temporary local JRE. Raw source documents and
translated outputs were not committed or included in docs. This is partial
Gate B evidence only: it does not prove Telegram bot upload UX, provider-backed
preview/full translation, manual DOCX Writer visual QA, server smoke,
restart/cancel/resume, retention/delete behavior, CI or full free-beta
readiness.

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

Issue #81 implementation slice on 2026-06-08: branch
`codex/issue-81-gate-b-restart-evidence` fixes interrupted persistent jobs
with already translated work units but no assembled output. Scheduler assembly
now also considers `interrupted` jobs that have available translated/cached
fragments, builds a `.partial` result, marks the job `partial`, and releases
the beta-safety reservation as `partial_assembly`. Interrupted jobs with no
translated fragments are skipped so My Books does not expose a source-only
partial download. Resume now returns terminal-failed work units to `pending` in
both SQLite and Postgres stores, and clears the old partial pointer on explicit
resume so a successful retry can assemble a final result instead of reusing the
stale partial output. Local verification passed focused scheduler/persistence/
Postgres regression tests, affected test files, targeted ruff, compile checks
for touched files, and full unittest discover in a clean temporary copy without
local `var/` runtime artifacts: 1366 tests `OK` with 31 skipped. The
in-worktree full unittest discover is polluted by existing local
`var/translation-runs` artifacts and fails one admin fixture-empty-state
assertion; runtime `var/` data was not modified. CI, server smoke, deploy,
bot/worker restart smoke on beta, and full Gate B readiness remain Unknown.

Issue #365 implementation slice on 2026-06-08: branch
`codex/issue-365-terminal-failure-partials` closes the remaining terminal
work-unit failure partial-result visibility gap from issue #365. Scheduler
assembly can now update a run log that was already safely marked `failed` by
terminal work-unit failure into `partial` when a real partial object is
assembled, while preserving the safe terminal failure error message and the
existing failure event diagnostics. Admin effective translation-log downloads
also resolve the partial/final result filename from persistent job output
metadata when durable state has advanced beyond stale `run.json`. Regression
coverage includes an EPUB terminal provider-failure scenario with an existing
translated work unit, `.partial.epub` assembly, retained terminal failure
diagnostics, preserved resume behavior through existing coverage, and
metadata-only effective export result filename coverage. Local verification
passed focused scheduler/admin/persistent-assembly/bot/run-log tests,
`PYTHONPATH=src python3 -m compileall src`, targeted `ruff --select F,I`, and
`git diff --check`. Full in-worktree unittest discover ran 1373 tests with 31
skipped and failed one known local-artifact assertion in
`test_reader_explorer_page_lists_sample_fixtures_under_advanced_nav` because
existing local `var/translation-runs` makes the page non-empty; runtime `var/`
data was not modified. CI, server smoke, deploy, real-file matrix, beta
runtime recovery, and full Gate B readiness remain Unknown.

Issue #370-#373 provider-boundary update on 2026-06-09: PRs #374-#377 are
merged. `docs/DECISIONS.md` records the approved JSON provider boundary
direction, rollback path and non-goals. Runtime now validates provider-facing
multi-block batch JSON with the strict
`{"translations":[{"id":"0","text":"..."}]}` shape, exact count, ordered ids,
no extra keys, non-empty text, protected-marker preservation and unsafe-output
rejection before converting validated JSON back to the existing internal
`translation_batch` representation. DeepSeek `response_format={"type":"json_object"}`
is enabled only for multi-block translation batches; plain-text and single-unit
requests remain unchanged. XML remains the internal/fallback/legacy path, with
stricter batch prompt/repair wording and strict XML validation preserved. Local
verification included targeted output-contract, prompt-security, DeepSeek-client
and translation-policy tests, compileall, targeted ruff and `git diff --check`;
a clean temporary full unittest run without local `var/` artifacts passed for
the shared provider slice. Visible GitHub Actions `Python checks` for PRs
#374-#377 were inspected as `SUCCESS`, but remain advisory per repo policy.
This does not enable beta features, strict function calling, chat prefix
completion, provider key/config changes, deployment changes, parallelism or
cost-cap changes, scheduler/database/runtime state changes, auth/security/
payment/legal/privacy changes, raw diagnostic copying, Gate B, beta readiness,
production readiness or deploy readiness. Live provider reliability, style
impact, token usage and retry impact remain `TBD` until owner-approved
provider-backed measurement exists.

Provider JSON malformed-output repair update on 2026-06-09: branch
`codex/json-batch-malformed-output-repair` adds a focused repair path for
DeepSeek `JSON_TRANSLATION_BATCH` responses that return HTTP 200 but contain
literal JSON control characters inside translated string values. The local
repair escapes only raw control characters inside JSON strings, then re-runs
the existing strict JSON batch validator for exact count, ordered ids, no extra
keys, non-empty text, protected-marker preservation and unsafe-output
rejection before converting to the existing internal `translation_batch` XML.
If local repair is not applicable for `invalid_json`, the single provider
repair retry now treats the malformed provider output as untrusted provider
output and asks DeepSeek to repair JSON shape/escaping instead of translating
the original source again. Safe security events remain metadata-only; raw
provider output stays confined to the approved owner-only provider IO
diagnostic boundary. Local verification passed focused DeepSeek-client and
output-contract tests, compileall, targeted ruff and `git diff --check`.
Full in-worktree unittest discover still fails the known local-artifact
Reader Explorer empty-state assertion because existing `var/translation-runs`
makes the admin page non-empty; runtime `var/` data was not modified.

Issue #388 provider JSON fallback update on 2026-06-11: branch
`codex/issue-388-malformed-provider-json` adds one bounded XML
`translation_batch` fallback after a multi-block JSON batch response remains
`invalid_json` after local control-character repair and one provider
JSON-format repair retry. The fallback retranslates the original untrusted
batch through the existing XML provider path, omits DeepSeek JSON
`response_format`, and accepts the result only through the existing strict XML
batch validator, including protected-marker preservation. Regression coverage
models the archive-shaped malformed JSON content with raw line breaks and
broken string structure, verifies the fallback request shape, covers
marker-preserving and missing-marker XML fallback outcomes, and checks that
fallback events remain metadata-only. Local verification passed focused
DeepSeek client, output-contract, prompt-security and translation-policy tests,
compileall and targeted ruff. Full in-worktree unittest discover last ran 1413
tests with 34 skipped and failed only the known local-artifact Reader Explorer
empty-state assertion because existing `var/translation-runs` makes the page
non-empty; runtime `var/` data was not modified. CI, server smoke, deploy,
provider-backed rerun of the EPUB, Gate B and release readiness remain Unknown.

Issue #385 final EPUB surface audit update on 2026-06-11: branch
`codex/385-epub-navigation-residue` adds a deterministic final-surface gate for
book-mode EPUB jobs targeting Russian or Ukrainian. The scheduler assembles the
final EPUB bytes for audit before exposing a `final_object_key`; only clean
final EPUBs are stored and attached as ready output. The audit covers XHTML body
headings, XHTML navigation/title, `toc.ncx` text and OPF title/language
metadata. If at least two high-confidence English navigation/heading residue
findings remain, the job is marked `failed` instead of clean `ready`, no final
or partial result pointer is exposed for user download, the beta-safety
reservation is released with `final_epub_surface_audit_failed`, and the run log
records only metadata-only gate diagnostics: phase, reason, counts, severity
and affected surface categories. Partial EPUB behavior remains unchanged, and
clean book-mode EPUB assembly remains `ready`. Local verification passed the
focused issue test set, compileall, targeted `ruff --select F,I`, and
`git diff --check`; full in-worktree unittest discover still fails only the
known local-artifact Reader Explorer empty-state assertion because existing
`var/translation-runs` makes the page non-empty. This does not add repair
retries, provider prompt/config changes, schema changes, deployment changes,
runtime data operations, raw diagnostic expansion, Gate B readiness or release
readiness.

EPUB standalone heading and audit-noise fix on 2026-06-11: branch
`codex/fix-epub-heading-audit` fixes the failure mode found after an
investigated EPUB job translated all work units but failed final assembly.
EPUB extraction no longer treats an XHTML heading as navigation only because
the same XHTML file lacks prose, so standalone spine headings remain body
translation blocks. The final book-mode output audit now masks bare
domain/path tokens such as `example.org/ebooks/12345`, matching the existing
URL masking so frontmatter/navigation link noise does not create false terminal
failures. Real untranslated headings and navigation labels still remain in
scope for the audit. Local verification passed focused persistent EPUB
assembly, scheduler final-audit, book-mode audit and translation-run-log tests,
compileall, targeted ruff and `git diff --check`. Full in-worktree unittest
discover ran 1421 tests with 34 skipped and failed only the known
local-artifact Reader Explorer empty-state assertion because existing
`var/translation-runs` makes the page non-empty; runtime `var/` data was not
modified. This does not repair existing failed jobs, rerun provider work,
change provider prompts/config, mutate scheduler/database/runtime state,
deploy, run server smoke, close Gate B, or claim release readiness.

Issue #367 ETA stabilization update on 2026-06-11: branch
`codex/issue-367-stabilize-long-eta` keeps the fix narrowly scoped to
Telegram progress ETA calculation/rendering. Worker-polled progress now keeps
the static baseline during the earliest low-sample warm-up, then allows
observed durable progress to replace the static baseline once enough fragments
are complete, and also trusts observed progress at high completion so a 99%
translation no longer shows hours remaining from the old static baseline.
Regression coverage includes baseline decay, early warm-up, later observed
throughput, and the 99%/short-remaining-time rendering case in Russian. Local
verification passed focused bot runtime/message tests, compileall, targeted
`ruff --select F,I`, and `git diff --check`. Full `ruff check` on the touched
files still reports pre-existing E501 line-length debt in
`tests/test_bot_messages.py`; those unrelated lines were not changed. This
does not change scheduler/provider capacity, database/runtime state, provider
retry/prompt behavior, partial assembly, raw diagnostics, deployment, Gate B or
release readiness.

Issue #393 EPUB RU localization cleanup update on 2026-06-11: PRs #398-#401
close child issues #394-#397. EPUB assembly now updates existing OPF/NCX/XHTML
`lang`/`xml:lang` attributes to the target language where the translated
content is Russian, while preserving the existing OPF `dc:language` update.
Russian EPUB text-node cleanup now localizes standard Gutenberg/front-matter
labels `Title:`, `Author:`, `Illustrator:`, `Language:` and `Credits:` without
rewriting the values after the colon; it also localizes the narrow
`FOOTNOTES:` section label across body, XHTML navigation and NCX surfaces, and
normalizes conservative straight double-quoted Russian dialogue to guillemets
without touching attribute-like or code-like snippets. The broader #384
`BOOK`/`CHAPTER` all-caps heading/protected-token work, cover image
translation, glossary/name/entity consistency, provider config/caps, scheduler
or database/runtime state, deployment, raw diagnostics, Gate B and release
readiness remain out of scope. Local verification passed focused
`tests.test_translation_postprocess`, `tests.test_format_adapters` and
`tests.test_translation_runner`, compileall, targeted `ruff --select F,I`,
`git diff --check`, and a combined synthetic EPUB probe for #393. Full
in-worktree unittest discover ran 1434 tests with 34 skipped and failed only
the known local-artifact Reader Explorer empty-state assertion because existing
local `var/translation-runs` makes the page non-empty; runtime `var/` data was
not modified. GitHub PR checks for #398-#401 were not reported by
`gh pr checks` at review time, so CI status remains Unknown.

Issue #413 DeepSeek Pro glossary/profile spike update on 2026-06-12: branch
`codex/issue-413-deepseek-pro-spike` adds a standalone bounded spike runner
and metadata-only report for the approved `deepseek-v4-pro` glossary/profile
role experiment. The live run used only the three approved TXT fixtures and
made 6 provider calls. Profile-advisor role outputs validated on all three
fixtures; glossary-editor output validated only on `sample_book.en.txt`.
Glossary-editor outputs for the two larger regression fixtures ended with
provider `length` and failed local validation as `invalid_json`. Observed
provider tokens were 62974 against the approved 60000-token cap, exposing that
the first local estimator under-reserved provider-reported prompt tokens; the
runner now uses a conservative reservation multiplier and observed-token guard
for future runs. Raw prompts/excerpts/provider responses were kept only in the
approved local untracked owner-only `outputs/issue-413-deepseek-pro-spike/`
diagnostic directory and are not copied into docs/issues/PR/release artifacts.
No runtime translation integration, provider runtime/config, cache,
database/state, deployment, retention, legal/privacy copy or release-readiness
claim was added. Further live provider work requires fresh exact owner
approval.

Translation export state update on 2026-06-03: admin translation-log downloads
now include metadata-only `effective_run.json` and `work_units.json` snapshots
built through the same persistent scheduler/work-unit overlay used by the
admin details UI/API. Raw `run.json` remains a sanitized lifecycle log and can
lag durable progress after worker interruption; Postgres-backed work units are
the effective progress source of truth when available. The regression fixture
models a stale run log with `0` raw fragments but `9/186` translated work units
and one terminal failed unit; coverage also includes a raw-only `ready`
fragment fallback so generated completed-unit counts stay aligned with raw run
summaries when no persistent store is available. Local verification on branch
`codex/fix-effective-translation-export`: focused admin/archive tests passed,
full `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1226 tests with
`OK (skipped=13)`, `PYTHONPATH=src python3 -m compileall src` passed, targeted
ruff on changed Python files passed, and `git diff --check` passed. CI status
remains Unknown until a PR/checks page is inspected. This does not mutate
runtime data, change schema/state, deploy code, read secrets/env files, or
claim broader Gate B/release readiness.

Translation export privacy update on 2026-06-07: the owner approved changing
downloaded translation-log archives into owner-only full diagnostic archives
when persistent work-unit state is available. The archive may now include
`raw_text_diagnostics.json` with raw source text, translated text, retry
attempts and provider failure diagnostics. `run.json`, `effective_run.json` and
`work_units.json` remain metadata-oriented snapshots so agents can distinguish
the original lifecycle log, the effective scheduler snapshot and the raw
diagnostic sidecar. This does not authorize copying raw excerpts into
telemetry, JSON APIs, support notes, GitHub issues, PR descriptions or release
artifacts.

Provider IO diagnostic update on 2026-06-07: after the latest
`pg2641-images-3.epub` failure could only be narrowed to DeepSeek
`malformed_response` / `unexpected_attribute` without the exact rejected body,
the owner approved saving exact provider request/response bodies for each
translation run. New run logs may include `provider_io_diagnostics.jsonl` with
the exact DeepSeek request JSON body and raw response body for each captured
transport exchange. This file is an owner-only raw diagnostic artifact included
by downloaded full diagnostic archives; it may contain prompt bodies, source
batch text and provider output, but must not contain the `Authorization` header
or API key and must stay out of telemetry, normal admin/API views, support
notes, GitHub issues, PR descriptions and release artifacts.

Issue #167 implementation slice on 2026-06-04: branch
`codex/issue-167-book-manuscript-policy-profile` generalizes
`book_manuscript` policy/profile context across persistent TXT, EPUB and DOCX
job plans. Policy snapshots now record a format-neutral
`book-manuscript-v1` profile and carry book/manuscript style context into
translation context memory; DOCX `document_form` keeps its existing
`docx-document-form-v1` profile and strict route. Duplicate-policy matching
uses the same profile helper so signatures stay aligned with persistent jobs.
Run-log policy snapshots retain `translation_mode` and
`translation_mode_profile` metadata, but do not serialize
`translation_context_memory`, avoiding document-derived `entity_choices`,
`source_text` or `target_text` in `run.json` and admin archives. Local
verification passed focused bot/planner/policy tests, targeted ruff,
compileall and full unittest discover with 1231 tests `OK (skipped=13)`. CI
status remains Unknown until a PR/checks page is inspected. This does not
change UI/copy, database/schema/state, provider configuration, runtime `var/`
data, supported formats, deployment, or release readiness.

Issue #162 implementation slice on 2026-06-04: branch
`codex/issue-162-provider-failure-diagnostics` adds safe provider failure
diagnostics for translation work-unit attempts. Worker/scheduler provider
failures now keep the existing retry policy but record a safe category such as
`rate_limited`, `timeout`, `unavailable_5xx`, `auth`, `billing`,
`malformed_response`, `unsafe_model_output`, `network`, `circuit_open` or
`provider_other` in work-unit attempt metadata and scheduler event payloads.
Admin translation details, trace and effective export can show the persisted
category, retry/status metadata, terminal reason, provider id, redacted channel
fingerprint and adaptive circuit snapshot even if live provider status later
returns to `ok`. Local verification passed focused provider/store/worker/
scheduler/admin tests, targeted `ruff --select F,I`, compileall,
`git diff --check`, and full unittest discover with 1243 tests `OK
(skipped=14)`. PR #279 visible GitHub `Python checks` succeeded. Issue #79 was
closed on 2026-06-04 after focused triage confirmed the provider-failure
diagnostics/user-message Gate B item is covered by #162/#279 plus existing safe
bot-message coverage. This does not add raw source/translated text, prompts,
provider payloads, tracebacks, API keys, full provider key ids, schema/table
migrations, runtime `var/` operations, deployment, provider
selection/retry-policy changes, payment behavior, scheduler/provider capacity
evidence, beta-server smoke evidence or full Gate B/release readiness.

Issue #133 implementation slice on 2026-06-04: branch
`codex/issue-133-costs-zero-usage` makes Admin -> Costs use read-only
persistent work-unit usage as the effective source when translation `run.json`
totals are stale zeroes. `Most expensive runs`, summary windows and
`Top users (all time)` now show non-zero prompt/completion/total token counts
and estimated model cost when persisted usage exists; runs with metadata but no
available usage totals are excluded from cost ranking and counted with an
explicit unavailable-usage note. Local verification passed focused admin costs
and admin route tests, full unittest discover with 1247 tests `OK
(skipped=14)`, `PYTHONPATH=src python3 -m compileall src`, targeted
`ruff --select F,I` on changed Python files and `git diff --check`. CI status
remains Unknown until a PR/checks page is inspected. This is read-only admin
analytics; it does not change beta safety budget accounting, payment/billing
ledgers, database schema/state, runtime `var/` data, deployment, auth/RBAC,
secrets/env files, provider behavior, raw text diagnostic boundaries or release
readiness.

EPUB/work-unit alignment fix on 2026-06-04: branch
`codex/fix-epub-work-unit-alignment` changes new multi-block persistent work
units to store a normalized `<translation_batch>` with stable
`translation_block id` values instead of plain `\n\n`-joined translated text.
Persistent assembly already maps batch ids back to source block ids, and the
run-log Text Diagnostics/Reader decodes stored batches back into readable
paragraph text for the owner-only diagnostic surface. This reduces paragraph
boundary drift during EPUB/DOCX assembly without schema changes, runtime data
mutation, deployment, provider configuration changes or release-readiness
claims. Existing legacy plain-text multi-block work units remain supported by
the assembly fallback.

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
- 2026-06-04: Issue
  [#169](https://github.com/ogirkoviylord/folioloom_main/issues/169)
  implementation slice is locally verified on branch
  `codex/issue-169-safe-run-metadata`. Book-mode translation run evidence now
  records metadata-only audit counters in `run.json` and `summary.md` when the
  run policy/stack identifies `book_manuscript` or `book-manuscript-v1`.
  Recorded evidence is limited to schema version, enabled flag, target language
  root, audited/finding counts, canonical codes and counts by code/category/
  severity for `untranslated_source_residue`, `english_navigation_residue`,
  `language_metadata_mismatch` and `provider_commentary`. Fragment artifacts
  still omit raw source text and translated text, audit metadata used for a
  finding is not persisted in fragment JSON, and scheduled worker success
  updates only existing metadata counters by `job_id`. Local verification: focused
  translation-run/admin-archive/book-audit tests passed; related
  `tests.test_bot_translation_service` passed; compileall over `src` passed;
  targeted `ruff --select F,I` passed; `git diff --check` passed; full
  `PYTHONPATH=src python3 -m unittest discover -s tests` ran 1236 tests with
  `OK (skipped=13)`. CI status remains Unknown until a PR/checks page is
  inspected. This does not block jobs, trigger provider retries, redesign
  admin, add raw snippets to logs/admin/artifacts, repair runtime data, deploy
  or claim release readiness.
- 2026-06-01: Owner approved permanent, owner-only raw translation text
  diagnostics after a failed EPUB translation showed that safe exports did not
  contain enough information to compare source work units, translated output and
  retry/error state. PR #179 added a metadata-only work-unit snapshot to normal
  translation details, plus a dedicated SSH-tunneled admin-session page for
  stored source/translated work-unit text; after merge/deploy the owner accepted
  this first interface as the ongoing direction. On 2026-06-07, the owner
  expanded the approved diagnostic surface to downloaded owner-only full
  diagnostic archives with `raw_text_diagnostics.json`; normal details,
  telemetry and JSON APIs remain metadata-only/redacted. Local verification for
  this slice is recorded in the task response. This does not authorize copying
  excerpts to issues/PRs/support notes, relax public admin restrictions or
  change Gate B release requirements.
- 2026-06-02: Owner additionally approved viewing raw provider prompt bodies in
  a dedicated owner-only diagnostic surface. This is a decision-level approval,
  and the 2026-06-07 provider IO diagnostic update now persists exact provider
  request/response bodies in `provider_io_diagnostics.jsonl` for translation
  run archives. Keep normal trace/evidence/telemetry/API surfaces
  metadata-only/redacted.
- 2026-06-06: Owner approved broad automatic raw provider diagnostics capture
  for pre-release development after job
  `job-9488146309f7434b9746580a6cc22d96` showed that safe metadata was
  insufficient to inspect exactly what was sent to and returned by the provider.
  The approved pre-release diagnostic intent is to retain the full analysis
  context for crashes and translation bugs, including source work-unit text,
  prompt bodies, provider user payloads, raw provider outputs, repair prompts,
  output-contract validation details and related job/work-unit state. This is
  owner/operator-only development diagnostics, not release-version telemetry or
  support/legal/privacy policy. Secrets must still be excluded, and the decision
  must be revisited before free beta/public release to define retention,
  consent, redaction and deletion behavior.
- 2026-06-02: Owner approved the issue #165 Book/Manuscript MVP contract
  direction: first MVP bar is structure preservation plus clean translation,
  with format-specific TXT/DOCX/EPUB expectations, zero provider commentary,
  target-language metadata updates where supported and no Gate B/release claims.
  Terminology/name handling (#204), read-only glossary (#205), editable glossary
  (#206), release-version analytics/consent policy (#207), future formats
  (#208) and stricter literary/editorial quality rubric (#209) are separate
  future issues. Owner also approved current/pre-release internal use of all
  uploaded files for analytics and product improvement; release-version behavior
  remains TBD.
- 2026-06-12: Owner clarified the future book glossary direction. Glossary is
  the default target for all book/manuscript translations, with later
  adaptation for document/form routes. The accepted direction is intentionally
  complex and should split glossary core, `book_translation_profile`, DeepSeek
  Pro role orchestration and raw diagnostics into separate architecture layers.
  DeepSeek Pro cost is not a blocker, but role contracts, schema/enums,
  evidence/confidence fields, failure/fallback behavior, translation snapshot
  boundaries and diagnostics ownership must be designed before implementation.
  Local code is not expected to prove semantic truth such as character gender;
  it should validate structure/evidence and flag uncertainty. Pre-release
  glossary/profile/provider/prompt/QA diagnostics may be broad and raw for
  owner debugging, excluding secrets and provider auth material. Release-version
  privacy, consent, retention, deletion and support/legal policy remain `TBD`.
- 2026-06-04: Owner clarified that future formats beyond TXT/DOCX/EPUB are a
  committed roadmap, not merely optional candidates. The committed future
  families are RTF (#4), FB2 (#23), PDF/OCR, HTML/HTM, ODT, legacy DOC, MOBI,
  AZW3/KPF and CBZ/CBR/DJVU. Current MVP and Gate B remain TXT/DOCX/EPUB;
  issue #208 owns prioritization and issue breakdown before any format-specific
  implementation approval.
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
  Original/Translation panes. Details/API surfaces remain metadata-only/redacted;
  downloaded owner-only full diagnostic archives may now include raw text via
  `raw_text_diagnostics.json`. Local verification passed `tests.test_admin_routes`,
  focused reader/diagnostics tests, targeted ruff for touched Python files and
  `PYTHONPATH=src python3 -m compileall src`. This does not add public routes,
  raw-text JSON APIs, arbitrary server-path browsing, runtime
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
- 2026-06-02: Issue
  [#216](https://github.com/ogirkoviylord/folioloom_main/issues/216) starts the
  second focused Reader/Text Diagnostics UX slice on branch
  `codex/issue-216-reader-qa-aids`, stacked after #214. The slice adds
  current-window search with safe highlighting, reader QA counts for empty
  source, missing translation and large source/translation length mismatch, and
  a metadata-only minimap over the loaded work-unit window. Local verification
  passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files and `PYTHONPATH=src python3 -m compileall src`. This
  does not search outside the loaded window, add public/user-facing access,
  expose raw text through JSON/API surfaces, add dependencies, access live
  runtime data, implement physical pages or claim full DOCX/EPUB fidelity.
  Downloaded owner-only full diagnostic archives may now include raw text via
  the approved `raw_text_diagnostics.json` sidecar.
- 2026-06-02: Issue
  [#218](https://github.com/ogirkoviylord/folioloom_main/issues/218) starts the
  first focused layout/indent diagnostics slice on branch
  `codex/issue-218-reader-indent-diagnostics`, stacked after #216. The slice
  adds current-window literal indentation evidence for source and translated
  work-unit text, a metadata panel that explicitly marks source-format style
  metadata as `Unknown`, and an opt-in editorial first-line indent preview for
  Reader only. Local verification passed focused reader/diagnostics regression
  coverage, `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`,
  targeted ruff for touched Python files and
  `PYTHONPATH=src python3 -m compileall src`. This does not extract EPUB CSS or
  DOCX paragraph style metadata, change stored text, add dependencies, access
  live runtime data, implement physical pages or claim full DOCX/EPUB fidelity.
- 2026-06-02: Issue
  [#220](https://github.com/ogirkoviylord/folioloom_main/issues/220) starts the
  first logical-page navigation slice on branch
  `codex/issue-220-reader-logical-pages`, stacked after #218. The slice lets
  run-log Reader/Text Diagnostics open a bounded work-unit window via a
  logical `page` query parameter, shows the current logical page plus loaded
  sequence range, and adds page jump/page-size controls that preserve search,
  invisible-character, sync-scroll and indent-preview flags. Local verification
  passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files and `PYTHONPATH=src python3 -m compileall src`. This
  keeps sequence-based links backwards-compatible and does not implement
  physical book pages, EPUB spine navigation, DOCX heading/chapter navigation,
  full-window search, public/user-facing access, live runtime data operations
  or release readiness.
- 2026-06-02: Issue
  [#222](https://github.com/ogirkoviylord/folioloom_main/issues/222) starts the
  first current-window QA filter slice on branch
  `codex/issue-222-reader-qa-filters`, stacked after #220. The slice adds a
  bounded `qa` query parameter and visible filter control for already-computed
  `all`, `empty_source`, `missing_translation`, `length_mismatch` and literal
  indent signals in run-log Reader/Text Diagnostics. Local verification passed
  focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files, `PYTHONPATH=src python3 -m compileall src` and
  `git diff --check`. This filters only the currently loaded work-unit window
  and does not add quality scoring, cross-window scanning, saved filters,
  annotations, public/user-facing access, live runtime data operations or
  release readiness.
- 2026-06-02: Issue
  [#224](https://github.com/ogirkoviylord/folioloom_main/issues/224) starts the
  first per-work-unit metrics slice on branch
  `codex/issue-224-reader-block-metrics`, stacked after #222. The slice shows
  source character count, translated character count and translation/source
  length ratio in run-log Reader blocks and Text Diagnostics row notes. Local
  verification passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files, `PYTHONPATH=src python3 -m compileall src` and
  `git diff --check`. The metrics are computed only from the currently loaded
  work-unit window and do not add semantic quality scoring, whole-book
  aggregation, saved metrics, annotations, public/user-facing access, live
  runtime data operations or release readiness.
- 2026-06-02: Issue
  [#226](https://github.com/ogirkoviylord/folioloom_main/issues/226) starts the
  first paragraph-structure diagnostics slice on branch
  `codex/issue-226-reader-paragraph-diagnostics`, stacked after #224. The slice
  adds source/translation line counts, blank-line counts, a
  `paragraph_mismatch` QA flag/filter and a Reader QA summary count for visible
  work units whose source and translation are both non-empty but differ in
  line/blank-line structure. Local verification passed focused
  reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files and `PYTHONPATH=src python3 -m compileall src`. The
  metrics stay current-window-only and do not add DOCX style extraction, EPUB
  CSS/layout reconstruction, semantic quality scoring, whole-book aggregation,
  public/user-facing access, live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#228](https://github.com/ogirkoviylord/folioloom_main/issues/228) starts the
  first QA issue navigation slice on branch
  `codex/issue-228-reader-qa-navigation`, stacked after #226. The slice adds a
  compact Reader-only QA issue rail for the currently visible work-unit window,
  listing existing QA flag labels by sequence and linking each item to the
  corresponding comparison block anchor. Local verification passed focused
  reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files and `PYTHONPATH=src python3 -m compileall src`. This
  does not add persistent annotations, whole-book aggregation, keyboard
  shortcuts, semantic quality scoring, public/user-facing access, publisher
  workspace, live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#230](https://github.com/ogirkoviylord/folioloom_main/issues/230) starts the
  first Reader keyboard navigation slice on branch
  `codex/issue-230-reader-keyboard-navigation`, stacked after #228. The slice
  lets the run-log Reader navigate to the existing Previous/Next logical window
  URLs with ArrowLeft/ArrowRight, while ignoring text fields, selects, buttons,
  links and contenteditable targets so forms and normal vertical scrolling keep
  their browser behavior. Local verification passed focused reader/diagnostics
  regression coverage, `PYTHONPATH=src python3 -m unittest
  tests.test_admin_routes`, targeted ruff for touched Python files and
  `PYTHONPATH=src python3 -m compileall src`. This does not add keyboard
  shortcuts for annotations/comments/QA issues, persistent preferences,
  public/user-facing access, publisher workspace, live runtime data operations
  or release readiness.
- 2026-06-02: Issue
  [#232](https://github.com/ogirkoviylord/folioloom_main/issues/232) starts the
  first Reader sticky position bar slice on branch
  `codex/issue-232-reader-sticky-position`, stacked after #230. The slice adds
  a compact sticky Reader-only current position/status bar showing the current
  logical page, loaded sequence range, page size, active QA filter, search
  state, special-character state, sync-scroll state and indent-preview state
  from the already loaded window and query parameters. Local verification
  passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files and `PYTHONPATH=src python3 -m compileall src`. This
  does not add saved views, persistent preferences, whole-book progress,
  localStorage/sessionStorage, public/user-facing access, publisher workspace,
  live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#234](https://github.com/ogirkoviylord/folioloom_main/issues/234) starts the
  first Reader QA issue step-controls slice on branch
  `codex/issue-234-reader-qa-step-controls`, stacked after #232. The slice adds
  Reader-only Previous issue / Next issue controls that move through existing
  QA issue anchors in the currently loaded work-unit window and update only the
  page hash/scroll position. Local verification passed focused
  reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files, `PYTHONPATH=src python3 -m compileall src` and
  `git diff --check`. The in-app browser connection was unavailable in this
  Codex session, so no manual browser smoke evidence was collected. This does
  not add whole-book issue traversal, persistent annotations, saved review
  state, public/user-facing access, publisher workspace, live runtime data
  operations or release readiness.
- 2026-06-02: Issue
  [#236](https://github.com/ogirkoviylord/folioloom_main/issues/236) starts the
  first Reader active QA highlight slice on branch
  `codex/issue-236-reader-active-qa-highlight`, stacked after #234. The slice
  makes Reader QA navigation visually stateful: selecting a QA issue by issue
  link, Previous issue / Next issue or page hash marks the active issue link
  and highlights the matching original/translation blocks in the currently
  loaded work-unit window. Local verification passed focused
  reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files, `PYTHONPATH=src python3 -m compileall src` and
  `git diff --check`. This does not add whole-book issue traversal, persistent
  annotations, saved review state, public/user-facing access, publisher
  workspace, live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#238](https://github.com/ogirkoviylord/folioloom_main/issues/238) starts the
  first Reader QA issue progress slice on branch
  `codex/issue-238-reader-qa-progress`, stacked after #236. The slice adds a
  compact Reader-only current-window QA progress chip that starts with the
  visible QA issue total and updates to `Issue X of N` when the owner selects a
  QA issue by issue link, Previous issue / Next issue or page hash. Local
  verification passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files, `PYTHONPATH=src python3 -m compileall src` and
  `git diff --check`. This does not add whole-book issue counts/traversal,
  persistent annotations, saved review state, public/user-facing access,
  publisher workspace, live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#240](https://github.com/ogirkoviylord/folioloom_main/issues/240) starts the
  first Reader search-hit navigation slice on branch
  `codex/issue-240-reader-search-hit-navigation`, stacked after #238. The slice
  adds Reader-only Previous hit / Next hit controls and a `Hit X of N` progress
  chip for already rendered search highlights in the currently loaded work-unit
  window. Local verification passed focused reader/diagnostics regression
  coverage, `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`,
  targeted ruff for touched Python files,
  `PYTHONPATH=src python3 -m compileall src` and `git diff --check`. This does
  not add whole-book search traversal, saved searches, persistent annotations,
  public/user-facing access, publisher workspace, live runtime data operations
  or release readiness.
- 2026-06-02: Issue
  [#242](https://github.com/ogirkoviylord/folioloom_main/issues/242) starts the
  first Reader search-hit row filter slice on branch
  `codex/issue-242-reader-search-hit-filter`, stacked after #240. The slice
  adds a Reader-only `search_hits=1` mode that narrows the already loaded
  work-unit window to source/translation rows containing the active search
  query, preserves existing Reader query controls and leaves Text Diagnostics
  behavior unchanged. Local verification passed focused reader/diagnostics
  regression coverage, `PYTHONPATH=src python3 -m unittest
  tests.test_admin_routes`, targeted ruff for touched Python files,
  `PYTHONPATH=src python3 -m compileall src` and `git diff --check`. Browser
  smoke was not available in the local app session because the browser agent
  was unavailable. This does not add whole-book search indexing/traversal,
  saved searches, persistent annotations, public/user-facing access, publisher
  workspace, live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#244](https://github.com/ogirkoviylord/folioloom_main/issues/244) starts the
  first Reader pane focus slice on branch
  `codex/issue-244-reader-pane-focus-mode`, stacked after #242. The slice adds
  Reader-only `pane_mode` controls for split, original-focus and
  translation-focus layouts so the owner can keep the before/after comparison
  visible while giving more horizontal space to one pane. Local verification
  passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted ruff
  for touched Python files, `PYTHONPATH=src python3 -m compileall src` and
  `git diff --check`. Browser smoke was not available in the local app session
  because the browser agent was unavailable. This does not add persisted
  preferences, editing, annotations, public/user-facing access, publisher
  workspace, live runtime data operations or release readiness.
- 2026-06-02: Issue
  [#246](https://github.com/ogirkoviylord/folioloom_main/issues/246) starts the
  first all-issues QA filter slice on branch
  `codex/issue-246-reader-all-issues-filter`, stacked after #244. The slice
  adds a shared owner-only `qa=issues` filter for Reader and Text Diagnostics
  so the current work-unit window can show any row with existing QA flags or
  literal-indent layout flags. Local verification passed focused all-issues
  filter coverage, `PYTHONPATH=src python3 -m unittest
  tests.test_admin_routes`, targeted `ruff --select F,I` for touched Python
  files, `PYTHONPATH=src python3 -m compileall src` and `git diff --check`.
  This does not add saved review state, annotations, exports, whole-book issue
  traversal, public/user-facing access, publisher workspace, live runtime data
  operations or release readiness.
- 2026-06-02: Issue
  [#248](https://github.com/ogirkoviylord/folioloom_main/issues/248) starts the
  first Reader layout issue navigation slice on branch
  `codex/issue-248-reader-layout-issue-nav`, stacked after #246. The slice
  makes existing literal-indent layout flags participate in Reader issue
  navigation, minimap warning state and block warning styling. Local
  verification passed focused reader/diagnostics regression coverage,
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`, targeted
  `ruff --select F,I` for touched Python files,
  `PYTHONPATH=src python3 -m compileall src` and `git diff --check`. This does
  not add new QA heuristics, whole-book issue traversal, saved review state,
  annotations, editing, public/user-facing access, publisher workspace, live
  runtime data operations or release readiness. Browser smoke was not available
  in the local app session because the browser agent was unavailable.
- 2026-06-02: Issue
  [#250](https://github.com/ogirkoviylord/folioloom_main/issues/250) starts the
  Reader sync-scroll drift bugfix on branch
  `codex/issue-250-reader-scroll-drift`, stacked after #248. Root-cause
  evidence: the previous sync script suppressed only one expected programmatic
  scroll value, so rounded/follow-up scroll events from the synced pane could
  be treated as user input and sync the active pane back. The slice replaces
  that with a short programmatic-scroll lock and tolerance before writing
  `scrollTop`. Local verification passed focused reader sync regression
  coverage, `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`,
  targeted `ruff --select F,I` for touched Python files,
  `PYTHONPATH=src python3 -m compileall src` and `git diff --check`. This does
  not change layout controls, persisted settings, public/user-facing access,
  publisher workspace, live runtime data operations or release readiness.
  Browser smoke was not available in the local app session because browser
  runtime discovery did not expose a usable JS execution tool.

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
- keep issue #165 as a docs-only Book/Manuscript MVP contract and keep
  terminology/name handling, complex glossary/profile architecture, analytics
  release policy, committed future formats and stricter quality criteria in
  separate future issues;
- treat issue #404 / #204A as the current no-code glossary architecture
  package at
  `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`.
  It defines the role graph, compact contract sketches, failure modes,
  translation snapshot boundary, diagnostics/provider boundaries and approval
  gates for #405-#413;
- treat issue #405 / #204B as the local glossary contract implementation:
  `src/translator_service/glossary_contracts.py` defines schema dataclasses,
  hard/soft/diagnostic vocabulary, status/category/strategy/gender/evidence
  enums, local validators and compact hash signatures; focused tests live in
  `tests/test_glossary_contracts.py`;
- treat issue #406 / #204C as the local deterministic glossary scanner
  implementation: `src/translator_service/glossary_scanner.py` scans existing
  TXT/DOCX/EPUB `FormatAdapterPlan` fixtures for soft/uncertain candidate
  names, quoted names, terms, aliases and metadata-only evidence refs; focused
  tests live in `tests/test_glossary_scanner.py`;
- treat issue #407 / #204D as the local book translation profile detector and
  rule-contract implementation: `src/translator_service/book_profile.py`
  defines deterministic profile detection over existing adapter plans,
  profile/rule dataclasses, confidence/uncertainty fields, local validators and
  profile-specific glossary rule data. Focused tests live in
  `tests/test_book_profile.py`;
- treat issue #408 / #204E as the local fake-output DeepSeek Pro glossary role
  JSON validator implementation: `src/translator_service/glossary_role_validators.py`
  validates approved role ids, `output_schema_version`, `diagnostics_ref`,
  status/enums, evidence refs, payload size caps, unsafe/raw-text fields,
  unsupported direct snapshot-effect claims, unsupported hard promotion,
  contradiction findings and cross-role profile disagreement using fake JSON
  only. Focused tests live in `tests/test_glossary_role_validators.py`;
- treat issue #409 / #204F as the local translation contract snapshot builder:
  `src/translator_service/translation_contract_snapshot.py` builds compact,
  deterministic glossary/profile planning snapshots from existing translation
  policy metadata plus glossary/profile signatures, selected rule ids,
  uncertainty markers and diagnostics policy ids. Focused tests live in
  `tests/test_translation_contract_snapshot.py`;
- treat issue #410 / #204G as the local per-work-unit glossary subset selector:
  `src/translator_service/glossary_selection.py` selects hard constraints plus
  relevant soft/diagnostic entries under deterministic prompt-budget limits and
  emits compact selection metadata with ids, reasons, token estimates and a
  selection signature. Focused tests live in `tests/test_glossary_selection.py`;
- treat issue #411 / #204H as the approved signatures-only cache/policy slice:
  `src/translator_service/translation_policy.py` defines an optional compact
  `TranslationPolicySignatureContext` for glossary/profile/snapshot/selection
  signatures, `src/translator_service/translation_cache.py` can include that
  context in cache keys, and
  `src/translator_service/translation_contract_snapshot.py` can derive a policy
  signature context from a compact translation snapshot. This does not inject
  glossary/profile data into prompts, call providers, mutate/delete runtime
  cache artifacts, change persistence/schema, change retention/TTL, add admin
  UI, or make release/privacy claims. Migration/stale-cache behavior remains
  `TBD`;
- treat issue #412 / #204I as the design-only owner-only glossary/profile
  diagnostics sidecar package at
  `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md`.
  It defines a dedicated sidecar boundary, raw-field manifest, compact vs
  raw-capable field classes, existing surface alignment, failure modes,
  required implementation tests and follow-up split. It does not implement
  storage, admin UI, archive inclusion, provider calls, retention/TTL changes,
  release/privacy/legal copy or raw diagnostics behavior. Retention, export,
  deletion and release-version policy remain `TBD`;
- treat issue #413 / #204J as the bounded DeepSeek Pro glossary/profile spike:
  profile-advisor outputs validated on all three approved fixtures, but larger
  glossary-editor outputs failed with provider `length` and `invalid_json`.
  The metadata-only report lives at
  `docs/superpowers/specs/2026-06-12-deepseek-pro-glossary-profile-spike-report.md`;
- treat issues #414-#416 / #204K-#204M as the chunked glossary-editor
  feasibility sequence after #413: #414 proves deterministic packetization,
  #415 proves strict local validation and merge/adjudication boundaries, and
  #416 tests the same boundary with bounded live DeepSeek Pro calls. This
  sequence is architecture evidence, not a finished runtime glossary. Current
  conclusion: chunking improves the provider-call shape, but the live editor
  still needs prompt/evidence iteration before any runtime integration;
- treat issue #414 / #204K as the local chunked glossary-editor packetizer:
  `src/translator_service/glossary_editor_packets.py` builds deterministic,
  compact/reference-oriented `GlossaryEditorPacket` objects from validated
  `GlossarySnapshot` and `BookProfileDetection` outputs, enforcing packet
  entry/evidence/token budgets, stable ids/signatures and degradation/skipped
  metadata. Focused tests live in `tests/test_glossary_editor_packets.py`.
  This does not call providers, integrate prompts/runtime/cache/storage,
  mutate persistence, expand diagnostics, add admin UI, change retention or
  claim release/privacy readiness;
- treat issue #415 / #204L as the local fake-output chunk validator and
  merge/adjudication contract:
  `src/translator_service/glossary_editor_chunk_outputs.py` validates one
  chunked glossary-editor JSON output against a specific
  `GlossaryEditorPacket`, rejects invalid packet/entry/evidence refs,
  unsupported enums, hard-layer promotion, oversized payloads and unsafe/raw
  keys, then merges valid chunk outputs into deterministic proposed metadata
  with duplicate/conflict/low-confidence/semantic-review findings. Focused
  tests live in `tests/test_glossary_editor_chunk_outputs.py`. This does not
  call providers, integrate prompts/runtime/cache/storage, mutate persistence,
  expand diagnostics, add admin UI, change retention or claim release/privacy
  readiness;
- treat issue #416 / #204M as the owner-approved bounded chunked DeepSeek Pro
  glossary-editor spike:
  `tools/deepseek_chunked_glossary_editor_spike.py` runs fake preflight or an
  approved live DeepSeek-compatible call set over the first READY packet per
  approved fixture, validates outputs through #415 and writes raw prompts,
  bounded excerpts and provider responses only to the approved untracked
  owner-only diagnostics directory. The live metadata-only report lives at
  `docs/superpowers/specs/2026-06-12-chunked-deepseek-pro-glossary-editor-spike-report.md`.
  The approved run made 3 calls, observed 16973 provider tokens, validated only
  the small `sample_book.en.txt` packet, and recorded two invalid larger-fixture
  outputs due to missing evidence refs. Recommendation: pivot or iterate the
  chunk prompt/evidence behavior before any runtime integration. This does not
  integrate prompts/runtime/cache/storage, mutate persistence, expand admin
  diagnostics, change retention or claim release/privacy readiness;
- treat issue #430 / #204N as the local fake-output evidence-contract
  iteration after #416:
  `tools/deepseek_chunked_glossary_editor_spike.py` now includes a compact
  `evidence_contract` in the chunked editor prompt and explicitly requires
  non-empty root, proposed-entry, rejected-entry and finding `evidence_refs`
  drawn from packet `allowed_evidence_ids`. Focused tests in
  `tests/test_chunked_deepseek_pro_spike.py` prove fake valid outputs for the
  three approved fixtures cite resolvable packet evidence refs, and fake
  missing-ref outputs fail validation and merge/adjudication with structured
  blocker findings. This is local prompt/validator evidence only; it does not
  call providers, integrate runtime prompts/cache/storage, mutate persistence,
  expand diagnostics, change retention or claim release/privacy readiness;
- treat issue #432 / #204P as the local metadata-only glossary/editor
  evaluation harness:
  `src/translator_service/glossary_evaluation.py` evaluates validated chunk
  outputs, merge/adjudication findings, packet budget metadata and optional
  metadata-only provider reports. The readiness gates measure schema validity,
  evidence-ref coverage, invalid chunk rate, blocker/warning findings,
  duplicate/conflict rate, budget overrun, `needs_review` rate, reduced-packet
  reducer decision coverage, reducer diagnostic/drop pressure and approved
  provider token caps. Passing local gates can support the next bounded
  provider retry, but fake/local evidence alone does not approve runtime
  architecture review or runtime integration. Focused tests live in
  `tests/test_glossary_evaluation.py`. This does not call providers, judge
  semantic truth, integrate runtime prompts/cache/storage, mutate persistence,
  expand diagnostics, change retention or claim release/privacy readiness;
- treat issue #433 / #204Q as the no-code runtime glossary integration
  architecture boundary:
  `docs/superpowers/specs/2026-06-12-runtime-glossary-integration-architecture.md`
  names future job-planning, work-unit selection, prompt-policy, cache/signature
  and diagnostics touchpoints, plus fallback behavior for invalid outputs,
  missing evidence, low confidence, budget exhaustion, provider failure and
  contradictory role outputs. Runtime prompt/cache/storage/database/admin/
  retention/provider behavior remains disabled and requires follow-up owner
  approval;
- treat issue #431 / #204O as the owner-approved bounded chunked DeepSeek Pro
  glossary-editor retry after the #430 evidence-contract fix:
  `docs/superpowers/specs/2026-06-12-bounded-chunked-deepseek-pro-glossary-editor-retry-report.md`
  records metadata-only results. The approved live run made 3 calls over the
  first READY packet per approved fixture, observed 19592 provider tokens,
  validated only the small `sample_book.en.txt` packet, and recorded two
  invalid larger-fixture outputs due to provider `length` completions and
  invalid JSON. Recommendation: pivot or iterate the chunk prompt/packet shape
  before runtime integration. Raw prompts, bounded excerpts and provider
  responses remain only in
  `outputs/issue-431-bounded-chunked-glossary-editor-retry/<timestamp>/`,
  which is local owner-only and untracked. This does not integrate prompts/
  runtime/cache/storage, mutate persistence, expand admin diagnostics, change
  retention or claim release/privacy readiness;
- treat issue #434 / #204R as the approved owner-only glossary/profile
  diagnostic sidecar foundation:
  `src/translator_service/glossary_profile_diagnostics.py` defines the
  dedicated `glossary_profile_diagnostics.json` schema/version/scope,
  owner-only access boundary, raw-field manifest validation, secret exclusion,
  metadata-only summary and file read/write boundary. Focused tests live in
  `tests/test_glossary_profile_diagnostics.py`. This does not add admin UI,
  public/user diagnostics, live provider calls, runtime prompt behavior,
  database/schema/cache/scheduler mutation, archive inclusion, retention/
  export/delete implementation or release/privacy claims. Retention, export,
  deletion and release-version policy remain `TBD`;
- treat issue #435 / #204S as the approved disabled-by-default
  fake-runtime/shadow glossary planning path:
  `src/translator_service/glossary_runtime_shadow.py` builds compact shadow
  metadata from TXT fixture content using the local glossary scanner, profile
  detector, translation contract snapshot builder, subset selector and policy
  signature helpers. Focused tests live in
  `tests/test_glossary_runtime_shadow.py`. Default behavior is disabled and
  returns existing-translation fallback metadata; enabled test/shadow planning
  changes no normal translation prompts, makes no live provider calls, mutates
  no cache/database/scheduler/work-unit/storage/admin state, and makes no
  release/privacy claims;
- treat issue #436 / #204T as the release-policy blocker for glossary/profile
  diagnostics:
  release-version privacy, consent, retention, deletion, support and
  legal/privacy behavior remain `TBD`/blocking. Pre-release owner-only
  diagnostics remain allowed only for explicitly approved bounded local runs or
  dedicated owner-only diagnostic surfaces. This does not approve retention/
  delete/export implementation, public/legal copy, support artifacts, release
  telemetry, runtime behavior or release/privacy readiness;
- treat issue #444 / #204U as the local metadata-only reduced-glossary pressure
  report foundation:
  `src/translator_service/glossary_pressure_report.py` builds advisory pressure
  reports from existing TXT/DOCX/EPUB `FormatAdapterPlan` metadata, local
  glossary scanner output, book profile detection and glossary-editor packet
  metadata. Reports include plan/candidate/profile/packet counts,
  distributions, signatures and advisory findings for candidate volume, packet
  count, token pressure, profile uncertainty and missing evidence. Focused
  tests live in `tests/test_glossary_pressure_report.py`. This does not call
  providers, integrate runtime prompts/cache/storage/admin, mutate persistence,
  expand diagnostics, change retention or claim release/privacy readiness;
- treat issue #450 / #204AA as the disabled-by-default reduced shadow runtime
  planning rehearsal:
  `src/translator_service/glossary_runtime_shadow.py` uses the local reducer's
  retained glossary snapshot for enabled shadow planning and emits compact
  source/reduced glossary signatures, reducer signature/count metadata,
  per-work-unit budget status and fallback reason codes. Focused tests live in
  `tests/test_glossary_runtime_shadow.py`. This does not call providers,
  inject glossary context into normal prompts, mutate cache/database/scheduler/
  work-unit/storage/admin/retention state, change user-visible behavior or
  claim release/privacy readiness;
- treat issue #451 / #204AB as the no-code reduced glossary runtime
  go/no-go review:
  `docs/superpowers/specs/2026-06-12-reduced-glossary-runtime-go-no-go.md`
  records NO-GO for normal runtime glossary prompt integration now, GO only
  for local metadata-only/shadow rehearsal, and NEEDS ITERATION after #449
  mixed live evidence. Prompt integration, cache behavior, storage/admin
  diagnostics, retention/export/delete and release/privacy claims remain behind
  separate owner approval gates;
- treat issue #461 / #204AC as the local reduced packet-budget hardening
  iteration:
  `src/translator_service/glossary_editor_packets.py` now keeps the full-scan
  default packet budget unchanged while using a more conservative default only
  for reducer-backed packets, records packet split reason codes, and preserves
  reducer policy/signature/count metadata. Focused tests live in
  `tests/test_glossary_editor_packets.py` and
  `tests/test_deepseek_chunked_glossary_editor_spike.py`. This does not call
  providers, integrate normal runtime prompts, mutate cache/storage/database/
  scheduler/admin/retention state, prove semantic glossary truth or claim
  release/privacy readiness;
- treat issue #462 / #204AD as local fake failure-mode coverage for reduced
  packet retries:
  `tools/deepseek_chunked_glossary_editor_spike.py` keeps provider `length`,
  timeout and missing-usage outcomes as metadata-only failures or `Unknown`
  usage in reports, while validators/evaluation reject truncated JSON as
  structured invalid chunks. Focused tests live in
  `tests/test_glossary_editor_chunk_outputs.py`,
  `tests/test_glossary_evaluation.py` and
  `tests/test_deepseek_chunked_glossary_editor_spike.py`. This does not call
  providers, add repair behavior, integrate runtime prompts, mutate cache/
  storage/database/scheduler/admin/retention state or claim release/privacy
  readiness;
- treat issue #463 / #204AE as the metadata-only local/fake readiness report
  after #461/#462:
  `docs/superpowers/specs/2026-06-13-reduced-glossary-readiness-after-packet-fixes.md`
  records that the approved four-input fake run passes schema validity,
  evidence-ref coverage, invalid chunk, blocker, duplicate/conflict, budget
  overrun and reducer decision coverage gates, but fails default readiness on
  warning findings, `needs_review_rate=1.0` and EPUB reducer diagnostic/drop
  pressure `0.967801` against the default `0.95` threshold. This does not call
  providers, integrate runtime prompts/cache/storage/admin, mutate persistence,
  prove semantic truth or claim release/privacy readiness;
- treat issue #464 / #204AF as the owner-approved bounded post-fix provider
  retry:
  `tools/deepseek_chunked_glossary_editor_spike.py` has an issue-specific
  `--issue-464-reduced` boundary and diagnostics root, and
  `docs/superpowers/specs/2026-06-13-reduced-glossary-editor-post-fix-retry-report.md`
  records that the owner explicitly deferred the #463 failed local gates before
  the run. The live retry validated all four approved reduced packets with
  provider `finish_reason=stop`, provider-reported usage present and observed
  tokens within the approved cap; merge/adjudication still produced warning-only
  duplicate/low-confidence semantic findings. This is provider-boundary
  evidence only and does not integrate runtime prompts, mutate cache/storage/
  database/scheduler/admin/retention state, prove semantic truth or claim
  release/privacy readiness;
- treat issue #465 / #204AG as the owner-approved design-only glossary runtime
  cache policy decision:
  `docs/superpowers/specs/2026-06-13-glossary-runtime-cache-policy-decision.md`
  and `docs/DECISIONS.md` record that the first disabled/default-off
  glossary-injected enabled/test-path adapter must bypass cache, while default
  runtime behavior and existing non-glossary cache behavior remain unchanged.
  Compact glossary/profile/snapshot/selection signatures may be emitted only
  as metadata for planning, diagnostics and future cache-key design. This does
  not implement code, mutate cache/database/storage/scheduler/admin/retention
  state, run providers, integrate prompts or claim release/privacy readiness.
  Future glossary-aware cache keys require a separate approved issue;
- treat issue #466 / #204AH as the disabled-by-default glossary prompt-policy
  adapter decision contract: `src/translator_service/translation_policy.py`
  now accepts compact reduced glossary shadow metadata in an enabled/test path,
  emits compact policy signature context and selected entry ids when ready,
  requires cache get/put bypass for glossary-injected enabled/test-path units,
  and falls back for missing, disabled, invalid, low-confidence, empty or
  over-budget glossary data. Default normal translation prompts, provider
  calls, cache/storage/database/scheduler/admin/retention state, user-visible
  behavior and release/privacy/legal/support claims remain unchanged;
- treat issue #474 as the first controlled runtime battle-test implementation
  slice after #473: `src/translator_service/translation_runner.py` now accepts
  a default-off glossary runtime adapter hook for DOCX/EPUB translation calls,
  computes compact adapter decisions from already-built shadow glossary
  metadata, and can emit compact in-process metadata through an explicit test
  callback. READY enabled/test-path units request cache get/put bypass per
  #465/#466, while disabled/fallback paths keep existing cache behavior.
  Normal prompts, provider calls, durable cache/storage/database/scheduler/
  admin/retention state, user-visible behavior and release/privacy/legal/
  support claims remain unchanged;
- treat issue #475 / #204AK as the local glossary prompt-context formatter
  contract only: `src/translator_service/glossary_prompt_context.py` formats
  compact selected glossary entries as escaped, bounded, untrusted reference
  data for future controlled tests, and returns metadata-only included/omitted
  entry and field-trim information. It does not integrate with normal prompts,
  call providers, change cache behavior, mutate durable state/storage/admin/
  retention behavior, prove semantic glossary truth or claim release/privacy
  readiness;
- treat issue #476 / #204AL as the disabled/test-only fake runtime glossary
  prompt rehearsal slice: `src/translator_service/translation_runner.py` can
  prefix DOCX/EPUB fake-provider requests with a bounded glossary context only
  when the explicit runtime hook and `prompt_rehearsal_enabled` test flag are
  enabled and the adapter decision is READY. The rehearsal path uses the #475
  formatter, keeps compact metadata only in ordinary callbacks, and proves
  cache bypass/fallback behavior with local stubs. Normal/default prompts,
  live provider calls, durable cache/storage/database/scheduler/admin/retention
  state, user-visible behavior and release/privacy/legal/support claims remain
  unchanged;
- treat issue #477 / #204AM as the first bounded glossary runtime provider
  smoke only: `tools/glossary_runtime_provider_smoke.py` now enforces the
  approved #477 inputs/targets/call cap/token cap/model/diagnostics boundary,
  runs fake preflight, and writes owner-only raw diagnostics under
  `outputs/issue-477-bounded-glossary-runtime-provider-smoke/`. The metadata
  report records that 3 approved TXT runtime smoke calls validated, while the
  approved EPUB RU/UK calls ended with provider `length` and local
  `truncated_output`/`external_text` validation failures. This is provider-
  boundary evidence only; normal runtime prompt rollout, cache reuse, durable
  state/storage/admin/retention behavior, user-visible behavior and release/
  privacy/legal/support claims remain unapproved;
- prepare the owner-approved internal/dev before-after reader in scoped issues,
  continuing after the locally verified #181 TXT report slice with #182 generic
  DOCX/EPUB block model and #183/#184 renderer spikes;
- держать payments, public production, public admin и committed future formats
  вне текущего MVP/release scope.
- Committed future formats beyond TXT/DOCX/EPUB are RTF (#4), FB2 (#23),
  PDF/OCR, HTML/HTM, ODT, legacy DOC, MOBI, AZW3/KPF and CBZ/CBR/DJVU. Issue
  #208 owns prioritization and issue breakdown; authorized fixtures, supported
  subsets, dependency impact and verification depth remain `TBD` until
  format-specific planning.

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

- Date: 2026-06-13.
- Change: Issue #474 adds a default-off glossary runtime adapter hook in
  `src/translator_service/translation_runner.py`, with focused DOCX cache/
  prompt regression coverage in `tests/test_translation_runner.py`.
- Evidence: local tests cover disabled hook behavior with unchanged prompt and
  cache reuse, fallback hook behavior with default cache behavior, and READY
  enabled/test-path metadata that requests cache get/put bypass without adding
  glossary entries, signature context, raw source text or prompt bodies to the
  translation request.
- Follow-up: #474 is still a controlled test-path hook only. Do not infer
  normal runtime glossary prompt injection, live provider calls, glossary-aware
  cache reuse, durable state mutation, storage/admin/retention behavior,
  user-visible behavior, semantic truth or release/privacy/legal/support
  readiness from #474.

- Date: 2026-06-13.
- Change: Issue #475 / #204AK adds a local bounded glossary prompt-context
  formatter in `src/translator_service/glossary_prompt_context.py`, with
  focused tests in `tests/test_glossary_prompt_context.py`.
- Evidence: local tests cover deterministic selected-entry ordering, escaping
  of delimiter/injection-like text, untrusted-reference framing, entry/token/
  character budget omissions, raw-capable mapping field rejection, field trim
  metadata and invalid formatter config.
- Follow-up: #475 is formatter-contract evidence only. Do not infer runtime
  prompt integration, live provider calls, cache behavior changes, durable
  state mutation, storage/admin/retention behavior, semantic truth or release/
  privacy/legal/support readiness from #475.

- Date: 2026-06-13.
- Change: Issue #476 / #204AL adds a disabled/test-only fake runtime glossary
  prompt rehearsal path in `src/translator_service/translation_runner.py`, with
  focused DOCX/EPUB coverage in `tests/test_translation_runner.py`.
- Evidence: local tests cover READY rehearsal prompts that include the bounded
  #475 glossary context only when `prompt_rehearsal_enabled` is set, cache
  get/put bypass for glossary-injected READY test units, disabled/fallback
  behavior that keeps the existing prompt/cache path, and metadata callbacks
  that omit raw prompt/source/translation bodies.
- Follow-up: #476 is fake/local rehearsal evidence only. Do not infer normal
  runtime glossary prompt injection, live provider calls, glossary-aware cache
  reuse, durable state mutation, storage/admin/retention behavior, user-visible
  behavior, semantic truth or release/privacy/legal/support readiness from
  #476.

- Date: 2026-06-13.
- Change: Issue #477 / #204AM adds a standalone bounded glossary runtime
  provider smoke runner in `tools/glossary_runtime_provider_smoke.py`, focused
  tests in `tests/test_glossary_runtime_provider_smoke.py`, and a metadata-only
  report at
  `docs/superpowers/specs/2026-06-13-glossary-runtime-provider-smoke-report.md`.
- Evidence: fake/dry preflight ran first with 5 fake calls. The approved live
  run made 5 calls to `deepseek-v4-pro`, observed 18,710 provider tokens
  against the approved 50,000 cap, validated the three approved TXT runtime
  smoke calls, and failed the approved EPUB RU/UK runtime smoke calls with
  provider `finish_reason=length` and local validation issue codes
  `truncated_output` and `external_text`.
- Follow-up: #477 recommends iterating the runtime prompt/selection budget
  before rollout. Do not infer normal runtime glossary prompt rollout,
  glossary-aware cache reuse, durable state mutation, storage/admin/retention
  behavior, user-visible behavior, semantic truth or release/privacy/legal/
  support readiness from #477.

- Date: 2026-06-13.
- Change: Issue #466 / #204AH adds a disabled-by-default glossary
  prompt-policy adapter decision contract in
  `src/translator_service/translation_policy.py`, with focused tests in
  `tests/test_translation_policy.py` and `tests/test_glossary_runtime_shadow.py`.
- Evidence: local tests cover default-off behavior, unchanged system prompt when
  disabled, compact enabled/test-path policy signature and selected entry ids,
  #465 cache-bypass semantics for glossary-injected enabled/test-path units,
  fallback for missing/disabled/fallback/invalid/low-confidence/over-budget/
  empty data and no raw diagnostic fields in adapter payloads.
- Follow-up: this is still runtime-adjacent planning metadata only. Do not infer
  normal runtime glossary prompt injection, glossary-aware cache reuse,
  provider calls, durable state mutation, storage/admin/retention behavior,
  semantic truth or release/privacy/legal/support readiness from #466.

- Date: 2026-06-13.
- Change: Issue #464 / #204AF adds issue-specific bounded post-fix reduced
  provider retry support to
  `tools/deepseek_chunked_glossary_editor_spike.py` and records the
  metadata-only report at
  `docs/superpowers/specs/2026-06-13-reduced-glossary-editor-post-fix-retry-report.md`.
- Evidence: owner approval in GitHub issue #464/comment thread explicitly
  defers the #463 failed local gates for this bounded retry. Fake/dry preflight
  completed four calls with 12737 fake observed tokens. The live retry used
  four calls, validated all four approved packets, had provider `finish_reason`
  `stop` for every call, recorded provider usage for every call, used 21053 /
  40000 observed tokens, reserved 31764 / 40000 local tokens and produced no
  invalid chunks or merge blockers. Merge/adjudication still recorded warning-
  only findings: one `duplicate_entry_output` and eight
  `low_confidence_semantics`.
- Follow-up: #466 may use this as metadata-only provider-boundary evidence
  after #464 is merged and reviewed. Do not infer normal runtime prompt
  integration, cache reuse, storage/admin diagnostics expansion, retention/
  delete/export behavior, semantic truth or release/privacy/legal/support
  readiness from #464.

- Date: 2026-06-13.
- Change: Issue #465 / #204AG records the owner-approved glossary runtime
  cache policy decision in `docs/DECISIONS.md` and
  `docs/superpowers/specs/2026-06-13-glossary-runtime-cache-policy-decision.md`.
- Evidence: owner approval in GitHub issue #465 selects cache bypass for the
  first glossary-injected enabled/test-path adapter. Existing code evidence
  shows compact signature context support in `translation_policy.py` and
  optional cache-key inclusion in `translation_cache.py`, but #465 makes those
  signatures metadata-only for the first adapter and does not approve cache
  reuse.
- Follow-up: #466 may use this cache policy only if its own gates are satisfied
  or explicitly deferred. Do not implement glossary-aware cache keys, cache
  migration, runtime prompt rollout, provider calls, storage/admin/retention
  behavior or release/privacy claims from #465.

- Date: 2026-06-13.
- Change: Issue #463 / #204AE adds the metadata-only local/fake readiness
  report at
  `docs/superpowers/specs/2026-06-13-reduced-glossary-readiness-after-packet-fixes.md`.
  The report measures the post-#461/#462 reduced packet path over the three
  repo fixtures plus the owner-approved local EPUB input.
- Evidence: local fake validation completed four calls with 12737 fake observed
  tokens. Structural gates passed for schema validity, evidence-ref coverage,
  invalid chunk rate, blockers, duplicate/conflict rate, budget overruns and
  reducer decision coverage. Default local readiness still fails on warning
  findings, `needs_review_rate=1.0` and EPUB reducer diagnostic/drop pressure
  `0.967801` versus the default `0.95` threshold.
- Follow-up: #464 later proceeded only after the owner explicitly recorded a
  gate deferral for these failed metrics. Do not infer runtime prompt/cache/
  storage/admin/retention/release readiness from #463.

- Date: 2026-06-13.
- Change: Issue #462 / #204AD adds local fake failure-mode coverage for
  reduced glossary-editor retries. The spike runner now preserves missing
  provider usage as `Unknown` instead of inventing `0`, and focused tests cover
  truncated JSON after `finish_reason=length`, timeout metadata failures and
  valid outputs with missing usage.
- Evidence: local validators/evaluation reject truncated JSON as structured
  invalid chunks and readiness blockers without copying raw bodies into
  metadata reports. Local verification passed focused chunk-output/evaluation/
  spike-runner tests, compileall, targeted ruff and `git diff --check` for the
  #462 diff.
- Follow-up: proceed to #463 metadata-only readiness reporting after #461 and
  #462 are merged. Do not add provider calls, runtime glossary prompt/cache
  behavior, provider repair behavior or release/privacy claims from #462.

- Date: 2026-06-13.
- Change: Issue #461 / #204AC hardens the local reduced glossary-editor
  packetizer in `src/translator_service/glossary_editor_packets.py`. The
  full-scan default budget remains unchanged, while reducer-backed packets use
  a conservative reduced default budget and record `split_reason_codes` in the
  packet payload. The #449 fake spike path now selects smaller reduced packets
  from the same local builder.
- Evidence: local fixture checks show the RU/UK regression full-scan packet
  shapes remain unchanged, while first reduced RU/UK packets shrink from about
  1.49k estimated prompt tokens to about 0.93k estimated prompt tokens with no
  skipped entries or evidence-ref degradation. Local verification passed
  focused packet/evaluation/spike-runner tests, compileall, targeted ruff and
  `git diff --check` for the #461 diff.
- Follow-up: proceed to #462 fake failure-mode coverage before any further
  provider retry. Do not enable runtime glossary prompt/cache behavior or make
  release/privacy claims from #461.

- Date: 2026-06-12.
- Change: Issue #449 / #204Z added #449-specific reduced-packet support to the
  standalone chunked glossary-editor spike runner in
  `tools/deepseek_chunked_glossary_editor_spike.py`, with focused coverage in
  `tests/test_deepseek_chunked_glossary_editor_spike.py`.
- Evidence: local fake/dry preflight over the three approved TXT fixtures plus
  the owner-approved local EPUB input completed with 4 fake calls and 15109
  observed fake tokens. The approved live retry used four provider attempts:
  the Russian packet returned `finish_reason=length` and invalid JSON, the
  Ukrainian packet timed out before provider usage metadata was available, and
  `sample_book.en.txt` plus the approved EPUB packet validated successfully.
  Known observed live provider tokens are 18271, with the timed-out Ukrainian
  usage `Unknown`. Focused tests, targeted ruff, compileall and `git diff
  --check` passed for the tooling/report change.
- Follow-up: do not enable runtime glossary prompt/cache behavior from #449.
  The reduced path still needs prompt/packet-budget iteration or a later
  architecture update before runtime proposals. Do not paste keys into shell
  commands or copy raw prompts, bounded excerpts, provider responses or
  translated text into ordinary docs/issues/PRs. No runtime prompt/cache/
  storage/database/admin/retention behavior or release/privacy claim is
  approved by #449.

- Date: 2026-06-12.
- Change: Issue #451 / #204AB added a no-code reduced glossary runtime
  go/no-go review at
  `docs/superpowers/specs/2026-06-12-reduced-glossary-runtime-go-no-go.md`.
- Evidence: review cites merged local reduced-glossary work #444-#448 and
  #450, #449 fake/dry evidence, prior live #416/#431 provider failures and the
  later #449 live retry report. Verdict remains NO-GO for normal runtime
  prompt/cache/storage/admin/release integration now; GO only for local
  metadata-only/shadow rehearsal. #449 live behavior is mixed rather than
  runtime-ready.
- Follow-up: decide whether another prompt/packet-budget iteration is needed
  before any runtime prompt/cache proposal. Release-version glossary/profile
  diagnostic policy remains `TBD`/blocking per #436.

- Date: 2026-06-12.
- Change: Issue #450 / #204AA extends the disabled-by-default shadow runtime
  planning helper in `src/translator_service/glossary_runtime_shadow.py` to use
  reducer-retained glossary candidates and emit compact reduced glossary,
  reducer and per-work-unit budget/fallback metadata.
- Evidence: local tests prove default disabled behavior remains unchanged,
  enabled shadow planning uses the reduced glossary signature, over-budget and
  missing/invalid reduced data fall back without prompt injection or state
  mutation, and serialized shadow payloads omit raw source text, prompt bodies,
  provider responses and translated text. Local verification passed focused
  shadow/selection/reducer tests, compileall, targeted ruff and `git diff
  --check`.
- Follow-up: keep #450 as metadata-only rehearsal until separate approval for
  real runtime prompt/cache/provider/storage/admin/retention behavior. #450
  does not prove semantic glossary truth or release/privacy readiness.

- Date: 2026-06-12.
- Change: Issue #448 / #204Y extended local reduced-packet fake-output
  validation coverage and `src/translator_service/glossary_evaluation.py`
  readiness gates with reducer decision coverage and reducer diagnostic/drop
  pressure metrics.
- Evidence: tests cover valid reduced packet fake outputs, unknown reduced
  packet/evidence refs, metadata-only reduced evaluation payloads, reducer
  drop-pressure threshold failure and missing reducer decision metadata
  failure. Local verification passed focused chunk-output/evaluation tests,
  compileall, targeted ruff and `git diff --check`.
- Follow-up: #448 local gates can support a bounded provider retry only after
  exact owner approval for #449. Do not add live provider calls, runtime prompt
  integration, cache/storage/database/scheduler/admin/retention behavior,
  semantic truth claims or release/privacy claims from #448 alone.

- Date: 2026-06-12.
- Change: Issue #447 / #204X updated
  `src/translator_service/glossary_editor_packets.py` so local glossary-editor
  packets can optionally be built from reducer-retained candidates, with
  reducer policy/signature/count metadata and reducer decision reasons included
  only on reduced packet payloads.
- Evidence: tests cover reduced packet construction, stable reduced signatures,
  reducer context payloads, reduced packet pressure on a noisy synthetic
  glossary, full-scan payloads without reducer fields, reduction/source
  signature mismatch rejection and metadata-only packet serialization. Local
  verification passed focused packet/reducer/chunk-output tests, compileall,
  targeted ruff and `git diff --check`.
- Follow-up: use reduced packets only as a local contract until #448 validates
  fake outputs/readiness gates. Do not add live provider calls, runtime prompt
  integration, cache/storage/database/scheduler/admin/retention behavior,
  ordinary translation-output changes or release/privacy claims from #447 alone.

- Date: 2026-06-12.
- Change: Issue #446 / #204W added a local metadata-only book-profile sanity
  gate in `src/translator_service/book_profile_sanity.py`, with focused
  coverage in `tests/test_book_profile_sanity.py`.
- Evidence: local tests cover clean profile pass-through, strong secondary
  profile review routes, false-confident legal/frontmatter blockers with
  bookish secondary signals, low-evidence warnings, invalid threshold handling
  and serialized metadata excluding synthetic raw profile/pressure text. Local
  verification passed focused sanity/profile/snapshot/packet tests, compileall,
  targeted ruff and `git diff --check`.
- Follow-up: use sanity results only as compact local metadata until separately
  approved downstream work consumes them. Do not add provider adjudication,
  runtime prompt/cache behavior, storage/database/scheduler/admin/retention
  behavior, user-facing glossary/profile behavior, semantic truth claims or
  release/privacy claims from #446 alone.

- Date: 2026-06-12.
- Change: Issue #445 / #204V added a local deterministic glossary candidate
  reducer in `src/translator_service/glossary_candidate_reducer.py`, with
  focused coverage in `tests/test_glossary_candidate_reducer.py`.
- Evidence: local reducer tests cover repeated important names/terms, quoted
  uncertain and frontmatter/navigation noise, deterministic caps and prompt
  budget pressure, stable signatures, invalid caps and serialized metadata that
  excludes synthetic raw source/target/pressure text. Local verification passed
  focused reducer/glossary/profile/packet tests, compileall, targeted ruff and
  `git diff --check`.
- Follow-up: use the reducer only as a local contract until separately approved
  downstream issues wire it into packet building or shadow planning. Do not add
  live provider calls, runtime prompt integration, cache/storage/database/
  scheduler/admin/retention behavior, user-visible glossary behavior, semantic
  truth claims or release/privacy claims from #445 alone.

- Date: 2026-06-12.
- Change: Issue #444 / #204U added a local metadata-only reduced-glossary
  pressure report builder in
  `src/translator_service/glossary_pressure_report.py`, with focused tests in
  `tests/test_glossary_pressure_report.py`.
- Evidence: local tests cover metadata-only report shape/signature,
  authorized TXT fixture planning, DOCX/EPUB-shaped adapter plans, advisory
  candidate/packet/token/profile findings and missing-evidence blockers
  without serializing raw source text. Local verification passed focused
  pressure/scanner/profile/packet tests, `PYTHONPATH=src python3 -m compileall
  src`, targeted `ruff --select F,I`, and `git diff --check`.
- Follow-up: use #444 measurements to inform #445 reducer defaults. Do not
  treat pressure metrics as semantic truth, provider readiness, runtime
  integration approval, release/privacy readiness, or permission to copy raw
  excerpts/prompts/provider responses into ordinary artifacts.

- Date: 2026-06-12.
- Change: Issue #436 / #204T records release-version glossary/profile
  diagnostic privacy, consent, retention, deletion, support and legal/privacy
  policy as `TBD`/blocking.
- Evidence: owner approval was given in the current Codex thread on
  2026-06-12 and recorded in GitHub issue #436. The docs-only update preserves
  pre-release owner-only diagnostics only for explicitly approved bounded local
  diagnostics or dedicated owner-only diagnostic surfaces.
- Follow-up: do not treat glossary/profile diagnostics, diagnostic sidecars,
  DeepSeek Pro role traces or translation contract snapshots as release
  telemetry, support artifacts, public/legal evidence or release/privacy-ready
  behavior until exact owner approval and required implementation/verification
  issues exist.

- Date: 2026-06-12.
- Change: Issue #435 / #204S added the disabled-by-default fake-runtime/shadow
  glossary planning helper in `src/translator_service/glossary_runtime_shadow.py`,
  with focused tests in `tests/test_glossary_runtime_shadow.py`.
- Evidence: tests prove default disabled behavior leaves runtime integration
  flags false, enabled fixture planning builds compact glossary/profile/
  snapshot/selection signatures without raw source text, prompt-budget
  exhaustion falls back without prompt injection, and invalid TXT content uses
  the existing translation fallback path. Local verification covered shadow,
  selection, snapshot, policy and cache tests.
- Follow-up: do not inject glossary/profile context into normal translation
  prompts, enable cache reuse changes, mutate durable runtime state, call live
  providers, add admin/storage/retention behavior or claim release/privacy
  readiness from #435 alone.

- Date: 2026-06-12.
- Change: Issue #434 / #204R added the owner-only glossary/profile diagnostic
  sidecar foundation in `src/translator_service/glossary_profile_diagnostics.py`,
  with focused tests in `tests/test_glossary_profile_diagnostics.py`.
- Evidence: tests cover compact sidecar validation, dedicated
  `glossary_profile_diagnostics.json` file read/write boundary, raw-capable
  field manifest requirements, metadata-only summary exclusion of raw values,
  security telemetry sanitization, secret/provider-auth rejection, owner-only
  access boundary enforcement and `TBD` retention policy enforcement.
- Follow-up: do not add admin UI, archive inclusion, runtime prompt behavior,
  live provider population, database/schema/cache/scheduler mutation,
  retention/export/delete behavior or release/privacy claims from #434 alone.

- Date: 2026-06-12.
- Change: Issue #431 / #204O ran the owner-approved bounded chunked DeepSeek Pro
  glossary-editor retry after #430 and added the metadata-only report at
  `docs/superpowers/specs/2026-06-12-bounded-chunked-deepseek-pro-glossary-editor-retry-report.md`.
- Evidence: fake/dry preflight passed locally. The live run used the three
  approved fixtures, first READY packet per fixture, max 3 calls, max 30000
  tokens, `deepseek-v4-pro`, local untracked owner-only diagnostic storage and
  bounded raw-text capture. It made 3 provider calls, observed 19592 provider
  tokens, validated only `sample_book.en.txt`, and recorded invalid JSON for
  the RU/UK regression packets because both completions ended with provider
  `finish_reason=length`. Merge/adjudication recorded 4 proposed entries, 2
  invalid packets, blocker `invalid_chunk` findings and warning
  `low_confidence_semantics` findings.
- Follow-up: pivot or iterate prompt/packet/completion budgeting before runtime
  integration. Do not add runtime translation integration, prompt rollout,
  cache/storage/database/admin integration, retention behavior,
  release/privacy claims or further live provider calls from #431 alone.

- Date: 2026-06-12.
- Change: Issue #433 / #204Q added a no-code runtime glossary integration
  architecture package at
  `docs/superpowers/specs/2026-06-12-runtime-glossary-integration-architecture.md`.
- Evidence: the package names future runtime touchpoints in job planning,
  work-unit selection, prompt policy, cache/signature handling and diagnostics;
  defines fallback behavior for invalid glossary/editor output, low confidence,
  missing evidence refs, budget exhaustion, provider failure and contradictory
  role outputs; and records follow-up order for #431, #434, #435 and #436.
- Follow-up: do not implement runtime glossary/profile prompts, cache reuse,
  storage/database/scheduler/admin diagnostics, retention behavior, live
  provider work or release/privacy claims from #433 alone. Those remain gated
  by explicit owner approvals and follow-up issues.

- Date: 2026-06-12.
- Change: Issue #432 / #204P added a local metadata-only glossary/editor
  evaluation harness in `src/translator_service/glossary_evaluation.py`, with
  focused coverage in `tests/test_glossary_evaluation.py`.
- Evidence: local tests cover a passing fake output for provider-retry
  readiness, missing-evidence invalid chunks, duplicate/conflicting outputs
  with `needs_review`, packet budget overrun and provider token-cap overrun.
  `docs/QUALITY_GATES.md` now records explicit local/fake -> provider-retry and
  provider-retry -> runtime architecture-review gates. Local verification
  passed focused evaluation/chunk-output/packet tests, compileall, targeted
  `ruff`, and `git diff --check`.
- Follow-up: use the evaluator as metadata-only readiness evidence for #431 and
  #433. Do not treat evaluator pass as semantic truth, runtime translation
  readiness, release/privacy readiness, provider approval, prompt rollout,
  cache/storage/database/admin integration or retention-policy approval.

- Date: 2026-06-12.
- Change: Issue #430 / #204N tightened the chunked glossary-editor
  prompt/evidence contract in
  `tools/deepseek_chunked_glossary_editor_spike.py` and expanded fake-output
  coverage in `tests/test_chunked_deepseek_pro_spike.py`.
- Evidence: focused local tests prove the prompt exposes a compact
  `evidence_contract`, fake valid outputs for the three approved fixtures cite
  resolvable packet evidence refs, and fake missing-ref outputs are rejected
  with `missing_evidence` validation issues plus blocker merge findings for
  invalid chunks and missing evidence refs. Local verification passed focused
  chunked-spike/chunk-output tests, `PYTHONPATH=src python3 -m compileall src`,
  targeted `ruff`, and `git diff --check`.
- Follow-up: #431 / #204O remains the next live retry candidate only after
  #430 is merged/verified and exact owner approval is recorded for fixtures,
  packet selection, call/token caps, provider/model, diagnostic storage and raw
  text policy. Do not add runtime translation integration, prompt rollout,
  cache/storage/database/admin integration, retention behavior,
  release/privacy claims or live provider calls from #430 alone.

- Date: 2026-06-12.
- Change: Issue #416 / #204M added a standalone bounded chunked DeepSeek Pro
  glossary-editor spike runner in
  `tools/deepseek_chunked_glossary_editor_spike.py`, focused tests in
  `tests/test_chunked_deepseek_pro_spike.py`, and a metadata-only report at
  `docs/superpowers/specs/2026-06-12-chunked-deepseek-pro-glossary-editor-spike-report.md`.
- Purpose: #414-#416 were done to see whether the invalid/oversized #413
  glossary-editor path could become a smaller packetized provider boundary with
  deterministic local validation before any runtime integration. The sequence
  produced useful architecture evidence, but not a production-ready glossary.
- Evidence: after owner approval for the three fixtures, first READY packet per
  fixture, max 3 calls, max 30000 tokens, `deepseek-v4-pro`, local untracked
  owner-only diagnostic storage and bounded raw-text capture, the live run made
  3 provider calls and observed 16973 provider tokens. The small
  `sample_book.en.txt` packet validated; the two regression-fixture packets
  failed local chunk validation because evidence refs were missing. Merge/
  adjudication recorded 4 proposed entries, 2 invalid packets, blocker findings
  for invalid chunks and missing evidence refs, and 0.0 conflict rate.
- Follow-up: pivot or iterate chunk prompt/evidence behavior before any runtime
  integration. Do not add provider runtime/config changes, prompt rollout,
  cache/storage/database/admin integration, retention behavior, release/privacy
  claims or further live provider calls without a fresh exact approval.

- Date: 2026-06-12.
- Change: Issue #415 / #204L added local fake-output validators and
  deterministic merge/adjudication for chunked glossary-editor outputs in
  `src/translator_service/glossary_editor_chunk_outputs.py`, with focused
  coverage in `tests/test_glossary_editor_chunk_outputs.py`.
- Evidence: local tests cover valid per-packet fake outputs, invalid packet
  refs, unknown entry refs, unsupported enum values, hard-layer promotion,
  missing evidence, oversized payloads, unsafe/raw output, duplicate/conflicting
  chunk proposals, invalid chunk exclusion, stable merge signatures and a fake
  output derived from a #413 fixture packet. Local verification passed focused
  chunk-output tests, glossary/profile related tests, compileall, targeted ruff
  and `git diff --check`.
- Follow-up: #416 live spike is now complete as a bounded metadata-only
  report. Do not add prompt/runtime/cache/storage integration, persistence/
  schema, diagnostic expansion, admin UI, retention behavior or release/privacy
  claims without a separate approved issue.

- Date: 2026-06-12.
- Change: Issue #414 / #204K added a local deterministic glossary editor
  packet contract and packet builder in
  `src/translator_service/glossary_editor_packets.py`, with focused coverage
  in `tests/test_glossary_editor_packets.py`.
- Evidence: local packet tests cover stable packet ids/signatures,
  compact/reference payloads without raw fixture excerpts, budget and reserved
  token enforcement, evidence-ref integrity, evidence-ref degradation,
  skipped-entry metadata and the three #413 TXT fixtures. Local verification
  passed focused packet tests, glossary/profile related tests, compileall,
  targeted ruff and `git diff --check`.
- Follow-up: proceed to #415 only as fake-output chunk validators and
  deterministic merge/adjudication tied to packet ids. Do not add live provider
  calls, prompt/runtime/cache/storage integration, persistence/schema,
  diagnostic expansion, admin UI, retention behavior or release/privacy claims.

- Date: 2026-06-12.
- Change: Issue #412 / #204I added a design-only owner-only glossary/profile
  diagnostics sidecar package at
  `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md`.
- Evidence: the package defines the proposed
  `glossary_profile_diagnostics.json` boundary, top-level schema,
  raw-text-field manifest, compact/reference-only fields, raw-capable sections,
  alignment with `raw_text_diagnostics.json` and
  `provider_io_diagnostics.jsonl`, failure behavior, implementation follow-up
  split and required future tests. This is docs-only; no code, provider calls,
  prompt/runtime integration, storage, admin UI, archive inclusion,
  retention/TTL behavior or release/privacy/legal claims changed.
- Follow-up: #413 must not start until exact owner approval records fixtures,
  max calls/tokens, provider/model, diagnostic storage and raw-text capture.
  Any #412 implementation remains a separate approved issue. Retention, export,
  deletion, consent, support and release-version legal/privacy behavior remain
  `TBD`.

- Date: 2026-06-12.
- Change: Issue #411 / #204H added signatures-only glossary/profile-aware
  cache and policy signature foundations. `translation_policy.py` now exposes
  `TranslationPolicySignatureContext` plus compact normalization/payload
  helpers; `translation_cache.py` accepts the optional context on get/put/cache
  key paths; `translation_contract_snapshot.py` can derive a policy signature
  context from a compact translation contract snapshot and optional work-unit
  selection signature.
- Evidence: owner approval for the signatures-only #411 scope was recorded in
  the current Codex thread on 2026-06-12. Local tests cover signature changes
  when glossary/profile/snapshot/selection/rule/prompt-contract inputs change,
  stability across ordering-only selected-rule noise, compact raw-text
  exclusion and existing translation-runner cache reuse. Local verification
  passed focused policy/cache/snapshot/glossary/profile tests,
  `tests.test_translation_runner`, targeted ruff, compileall and
  `git diff --check`.
- Follow-up: do not start #413 until exact owner approval records fixtures,
  calls/tokens, provider/model, diagnostic storage and raw-text capture.
  Future cache-key migration/stale-cache reuse behavior remains `TBD`; #465
  later decides only the first-adapter bypass policy.

- Date: 2026-06-12.
- Change: Issue #410 / #204G added a local deterministic per-work-unit glossary
  subset selector in `src/translator_service/glossary_selection.py`, with
  focused coverage in `tests/test_glossary_selection.py`.
- Evidence: local selection tests cover small/medium/large glossary budgets,
  hard constraints under tight budgets, deterministic repeated selection,
  empty glossary behavior, conflicting soft entries, profile-rule relevance,
  multi-work-unit anchor selection and compact metadata without synthetic raw
  source/target text. Local verification passed focused selection/glossary/
  scanner/profile/snapshot tests, compileall, targeted ruff and
  `git diff --check`.
- Follow-up: do not add live provider calls, prompt/runtime integration,
  persisted state, admin UI, raw diagnostic implementation, retention behavior
  or release/privacy claims outside separately approved issues.

- Date: 2026-06-12.
- Change: Issue #409 / #204F added a local deterministic translation contract
  snapshot builder in `src/translator_service/translation_contract_snapshot.py`,
  with focused coverage in `tests/test_translation_contract_snapshot.py`.
- Evidence: local snapshot tests cover required contract/version/signature
  fields, stable serialization across reordered rule/uncertainty ids,
  signature changes when glossary metadata changes, compact snapshots excluding
  synthetic raw source/target/profile excerpt text by default, rejection of
  non-compact rule and uncertainty markers, and explicit `TBD` retention
  policy. Local verification passed focused snapshot/policy/glossary/profile
  tests, compileall, targeted ruff and `git diff --check`.
- Follow-up: proceed to #410 only as per-work-unit glossary subset selector;
  do not add live provider calls, prompt/runtime/cache integration, persisted
  state, admin UI, raw diagnostic implementation, retention behavior or
  release/privacy claims.

- Date: 2026-06-12.
- Change: Issue #408 / #204E added local fake-output JSON validators for
  approved DeepSeek Pro glossary/profile roles in
  `src/translator_service/glossary_role_validators.py`, with focused coverage
  in `tests/test_glossary_role_validators.py`.
- Evidence: local role-validator tests cover valid glossary editor/profile
  advisor fake outputs, invalid JSON/root shape, missing evidence refs,
  unsupported enum values, oversized payloads, unsupported hard promotion,
  unsafe model-output strings, forbidden raw-text keys, blocking contradiction
  findings and cross-role profile disagreement. Local verification passed
  focused role/glossary/profile/output-safety tests, compileall, targeted ruff
  and `git diff --check`.
- Follow-up: proceed to #409 only as translation contract snapshot builder;
  do not add live provider calls, prompt/runtime/cache integration, persisted
  state, admin UI, raw diagnostic implementation or release/privacy claims.

- Date: 2026-06-12.
- Change: Issue #407 / #204D added a local deterministic book translation
  profile detector and profile-specific glossary rule contract in
  `src/translator_service/book_profile.py`, with focused coverage in
  `tests/test_book_profile.py`.
- Evidence: local profile tests cover literary-fiction detection with
  contextual name rules, scientific/academic detection with strict term rules,
  ambiguous/unknown and recognized-profile fallback rules requiring review,
  metadata-only evidence refs with no raw excerpts and validator rejection of
  invalid enum, confidence, missing-field and missing-evidence cases. Local
  verification passed focused profile/scanner/contract tests, compileall,
  targeted ruff and `git diff --check`.
- Follow-up: proceed to #408 only as fake-output DeepSeek role JSON validators;
  do not add live provider calls, prompt/runtime/cache integration, persisted
  state, admin UI, raw diagnostic implementation or release/privacy claims.

- Date: 2026-06-12.
- Change: Issue #406 / #204C added a deterministic local glossary
  candidate/evidence scanner in `src/translator_service/glossary_scanner.py`,
  with focused coverage in `tests/test_glossary_scanner.py`.
- Evidence: local scanner tests cover deterministic output, repeated names and
  terms, simple aliases, ambiguous single-token names with `unknown` gender and
  `ru_uk_morphology_tbd`, quoted names with metadata-only evidence refs, empty
  no-candidate documents, bounded evidence refs and unsupported PDF plans.
  Local verification passed focused scanner/contract tests, compileall,
  targeted ruff and `git diff --check`.
- Follow-up: proceed to #407 only as local book profile detector/rule contract
  work; do not add prompt/runtime/cache/storage integration, provider calls,
  admin UI, raw diagnostics implementation or release/privacy claims in #407.

- Date: 2026-06-12.
- Change: Issue #405 / #204B added local glossary contract schemas,
  validators and compact signatures in
  `src/translator_service/glossary_contracts.py`, with focused coverage in
  `tests/test_glossary_contracts.py`.
- Evidence: local validation covers required fields, enum values,
  hard/soft/diagnostic layer/status compatibility, evidence references,
  confidence ranges, source anchors, raw-excerpt gating and stable compact
  signatures that hash raw source/target strings instead of returning them.
  Local verification passed focused glossary contract tests, compileall,
  targeted ruff and `git diff --check`.
- Follow-up: proceed to #406 only as deterministic scanner work on authorized
  fixtures; do not add provider calls, prompt/runtime/cache/storage
  integration, admin UI, raw diagnostics implementation or release/privacy
  claims in #406.

- Date: 2026-06-12.
- Change: Issue #404 / #204A produced a no-code glossary architecture package
  at
  `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`.
  The package defines the book glossary role graph, compact schema sketches,
  hard/soft/diagnostic layers, local-vs-model judgment boundary, failure
  modes, translation snapshot boundary, owner-only diagnostics boundary,
  provider boundary and approval gates for #405-#413.
- Evidence: docs-only architecture package; no code, provider calls,
  persistence/schema/storage, admin/UI, runtime integration, deployment,
  payment, legal/privacy or release-readiness changes.
- Follow-up: #405-#412 now provide the local contract/scanner/profile/
  role-validator/snapshot/selector/signature/design foundations. Do not start
  #413 without exact provider-spike approval.

- Date: 2026-06-02.
- Change: Issue
  [#268](https://github.com/ogirkoviylord/folioloom_main/issues/268)
  persists owner-only Translation Reader review marks on branch
  `codex/issue-268-reader-persisted-marks`. The browser submits only
  `sequence` and mark state; the admin route resolves the selected work unit
  server-side and stores the marked original/source text, translated text,
  status and source block ids in run-scoped `reader_review_marks.json`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, and `git diff --check` passed. Visible
  GitHub Python checks for PR
  [#269](https://github.com/ogirkoviylord/folioloom_main/pull/269) passed.
- Follow-up: `reader_review_marks.json` is an owner-only raw diagnostic sidecar
  and is excluded from normal details/API/download archive surfaces by test.
  This slice does not add notes/comments, export reports, cross-run review
  state, database storage, public/user-facing reader access, publisher
  workspace, auth/RBAC changes, dependencies, deploy, or release readiness.
- Owner direction update: the earlier stop-after-#266 Reader ergonomics
  direction remains the default for broad Reader feature creep, but the owner
  explicitly resumed one narrow persistence slice for marked fragments and
  clarified that both original/source and translated text must be saved for
  marked items.

- Date: 2026-06-02.
- Change: Issue
  [#266](https://github.com/ogirkoviylord/folioloom_main/issues/266)
  adds current-page keyboard shortcuts for temporary Reader review marks on
  branch `codex/issue-266-reader-review-hotkeys`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, and `git diff --check` passed.
  Visible GitHub Python checks for PR
  [#267](https://github.com/ogirkoviylord/folioloom_main/pull/267) passed.
- Follow-up: keyboard-applied review marks are current-page DOM state only.
  This slice does not persist review marks, add cross-page review state, edit
  text, export review reports, add raw snippets to docs/issues or archives, add
  public/user-facing reader access, change auth/RBAC, access runtime data, add
  dependencies, deploy, or claim release readiness.
- Owner direction: stop the current Reader ergonomics push after this slice.
  Unfinished/deferred Reader ideas are persistent review state, cross-page
  completion, block notes/comments, review report export, stronger chapter/page
  outline and visual intra-block diff. Publisher/editor workspaces are not
  planned for immediate implementation; treat them as future TBD scope only.

- Date: 2026-06-02.
- Change: Issue
  [#264](https://github.com/ogirkoviylord/folioloom_main/issues/264)
  adds client-side unmarked review filtering and completion counts to the
  owner-only Translation Reader on branch
  `codex/issue-264-reader-unmarked-review-filter`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, and `git diff --check` passed.
  Visible GitHub Python checks for PR
  [#265](https://github.com/ogirkoviylord/folioloom_main/pull/265) passed.
- Follow-up: unmarked filtering and completion counts are current-page DOM state
  only. This slice does not persist review completion, add cross-page review
  state, edit text, export review reports, add raw snippets to docs/issues or
  archives, add public/user-facing reader access, change auth/RBAC, access
  runtime data, add dependencies, deploy, or claim release readiness.

- Date: 2026-06-02.
- Change: Issue
  [#262](https://github.com/ogirkoviylord/folioloom_main/issues/262)
  adds client-side Previous/Next navigation for temporary review marks in the
  owner-only Translation Reader on branch
  `codex/issue-262-reader-review-mark-navigation`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, `git diff --check` passed, and visible
  GitHub `Python checks` for PR #263 passed.
- Follow-up: review mark navigation is current-page DOM state only. This slice
  does not persist marks, filters or current step, add cross-page navigation,
  edit text, export review reports, add raw snippets to docs/issues or archives,
  add public/user-facing reader access, change auth/RBAC, access runtime data,
  add dependencies, deploy, or claim release readiness.

- Date: 2026-06-02.
- Change: Issue
  [#260](https://github.com/ogirkoviylord/folioloom_main/issues/260)
  adds client-side review mark counts and filters to the owner-only Translation
  Reader on branch `codex/issue-260-reader-review-mark-filters`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, `git diff --check` passed, and visible
  GitHub `Python checks` for PR #261 passed.
- Follow-up: review mark filters are current-page DOM state only. This slice
  does not persist marks or filters, change URL/server row selection, edit text,
  export review reports, add raw snippets to docs/issues or archives, add
  public/user-facing reader access, change auth/RBAC, access runtime data, add
  dependencies, deploy, or claim release readiness.

- Date: 2026-06-02.
- Change: Issue
  [#258](https://github.com/ogirkoviylord/folioloom_main/issues/258)
  adds client-only review marks to the owner-only Translation Reader on branch
  `codex/issue-258-reader-review-marks`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, `git diff --check` passed, and visible
  GitHub `Python checks` for PR #259 passed.
- Follow-up: review marks are current-page DOM state only. This slice does not
  persist marks, edit text, export review notes, add raw snippets to docs/issues
  or archives, add public/user-facing reader access, change auth/RBAC, access
  runtime data, add dependencies, deploy, or claim release readiness.

- Date: 2026-06-02.
- Change: Issue
  [#256](https://github.com/ogirkoviylord/folioloom_main/issues/256)
  adds active current-window outline navigation to the owner-only Translation
  Reader on branch `codex/issue-256-reader-active-outline`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, `git diff --check` passed, and visible
  GitHub `Python checks` for PR #257 passed.
- Follow-up: this slice does not add raw snippets, editing, persisted review
  state, public/user-facing reader access, auth/RBAC changes, runtime data
  access, dependencies, deployment or release-readiness claims.

- Date: 2026-06-02.
- Change: Issue
  [#254](https://github.com/ogirkoviylord/folioloom_main/issues/254)
  adds a metadata-only current-window block outline to the owner-only
  Translation Reader on branch `codex/issue-254-reader-block-outline`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, `git diff --check` passed, and visible
  GitHub `Python checks` for PR #255 passed.
- Follow-up: this slice does not add raw snippets to the outline,
  public/user-facing reader access, editing, persisted review state, auth/RBAC
  changes, runtime data access, dependencies, deployment or release-readiness
  claims.

- Date: 2026-06-02.
- Change: Issue
  [#252](https://github.com/ogirkoviylord/folioloom_main/issues/252)
  adds clickable owner-only Translation Reader QA/Layout metric filters on
  branch `codex/issue-252-reader-qa-metric-links`.
- Evidence: local verification passed:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes` ran 99 tests
  with `OK`, `PYTHONPATH=src python3 -m compileall src` passed,
  targeted `ruff --select F,I` passed, and `git diff --check` passed.
- Follow-up: keep future publisher/editor workspace work as separate
  owner-approved issues. This slice does not add public/user-facing reader
  access, new raw-text surfaces, auth/RBAC changes, runtime data access,
  dependencies, deployment or release-readiness claims.

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

- Question: What order should issue #208 use for committed future formats?
- Why it matters: RTF, FB2, PDF/OCR, HTML/HTM, ODT, legacy DOC, MOBI,
  AZW3/KPF and CBZ/CBR/DJVU expand parser, fixture, dependency, QA, privacy and
  support scope beyond the current TXT/DOCX/EPUB beta.
- Suggested options: prioritize low-parser-risk text formats first; prioritize
  user-demand formats first; run separate architecture spikes for PDF/OCR and
  image-heavy formats.
- Recommended default: keep current MVP on TXT/DOCX/EPUB and use #208 to rank
  committed future formats before opening implementation issues.

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
