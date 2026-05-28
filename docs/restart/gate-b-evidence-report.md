# Gate B Evidence Report - FolioLoom Free Closed Beta

Date: 2026-05-28

Task classification: docs-only / release-related evidence collection.

This report is evidence collection, not a release approval. A Gate B item is
release-ready only when evidence exists or the owner explicitly defers it in a
signed go/no-go note.

## 1. Release Type

Free closed beta.

## 2. Scope

In scope:

- Telegram-first trusted beta users.
- TXT, DOCX and EPUB uploads only.
- Authorized documents only, with rights confirmation before full processing.
- Free preview before full translation.
- Backend-first persistent jobs/work units, worker processing, progress,
  cancel/status/history/My Books flow, final or partial result.
- Invite-only beta allowlist, beta cost caps, admin kill switch and safe beta
  telemetry.
- SSH-tunnel-only owner/admin console.
- Backup/restore workflow evidence for beta readiness.

Explicitly out of scope:

- Payments, payment UI, paid jobs, paid beta, pricing changes and payment
  provider integrations.
- Public production, public admin exposure, public self-serve signup, public
  website/customer portal and public API.
- New formats beyond TXT/DOCX/EPUB, including PDF/OCR/MOBI/FB2/batch ZIP.
- Legal/privacy/AUP/refund/support claims for public production.
- Deployment or server operations without explicit human approval.

## 3. Executive Verdict

Verdict: Needs more verification.

Why: repository evidence confirms several foundation items, including invite-only
allowlist, rights confirmation, free preview, beta caps, kill switch, SSH-tunnel
admin policy, no-payments scope, safe beta telemetry, scoped upload
hardening/quarantine evidence for issue #73 and scoped local malware/AV
scanning evidence for issue #95, and release-wide logs/admin raw-text
redaction evidence for issue #78. Gate B still has release blockers without
stored evidence: TTL cleanup/delete
behavior, real-file TXT/DOCX/EPUB matrix, restart/cancel/resume scenarios,
capacity/provider-failure release evidence, EPUB/DOCX validation, Alerts MVP,
backups visibility, backup export verification, restore rehearsal,
and approved beta-server smoke.

No owner-approved Gate B deferrals were found in the inspected repository
documents.

## 4. Gate B Evidence Table

| Gate item | Status | Confirmed evidence | Missing evidence | Commands/artifacts | Human approval needed? | Risk / follow-up |
| --- | --- | --- | --- | --- | --- | --- |
| Rights confirmation is shown before full processing. | Pass | Checked in `docs/restart/release-gates.md`; described in `README.md`, `CURRENT_PROJECT_STATE.md`, `docs/DECISIONS.md`. | Current beta-server flow smoke not run in this task. | Last recorded full suite after rights gate: `Ran 856 tests`, `OK`; later issue #56 suite also passed. | Yes if legal/rights wording or data handling changes. | Preserve rights gate in bot-flow changes. |
| Free preview exists before full translation. | Pass | Checked in `docs/restart/release-gates.md`; evidence names PRs #57/#58/#59/#61/#67 and issue #56 local verification on 2026-05-16. | This proves the preview item only, not overall Gate B readiness. | Focused preview/bot/service suite `Ran 237 tests`, `OK`; full suite `Ran 1046 tests`, `OK`, `skipped=13`; compileall passed; `scripts/predeploy_check.sh` passed. | No for current evidence; yes for payment-adjacent preview changes. | Include preview in real-file/restart matrix. |
| Per-user cost caps/job limits are enforced by the Phase 4 operational beta safety guard. | Pass | Checked in `docs/restart/release-gates.md`; `README.md` Beta Safety / Cost Guard; `CURRENT_PROJECT_STATE.md`; `docs/DECISIONS.md`. | Current runtime cap smoke not run in this task. | Existing evidence references `src/translator_service/beta_safety.py`, `tests/test_beta_safety.py`, `tests/test_beta_safety_store.py`. | Yes for cap/concurrency/cost-policy changes. | Keep as release smoke and admin settings check. |
| Global cost caps are enforced by reservation-at-enqueue and scheduler claim guards. | Pass | Checked in `docs/restart/release-gates.md`; `README.md` and `docs/DECISIONS.md` describe reservation-at-enqueue and scheduler claim guards. | Current release run against beta config not recorded. | Existing beta safety and scheduler tests referenced in docs. | Yes for cap/provider/scheduler changes. | Verify with release-scoped cap tests before go/no-go. |
| Admin kill switch exists in Settings/Live visibility and stops new uploads/jobs and new scheduler claims without restart. | Pass | Checked in `docs/restart/release-gates.md`; `README.md` documents `BETA_TRANSLATIONS_PAUSED`; `CURRENT_PROJECT_STATE.md` describes admin/live visibility. | Current beta-server admin smoke not run in this task. | Existing admin/live/bot/scheduler tests referenced in docs. | Yes for admin/provider/scheduler behavior changes. | Include kill-switch check in server smoke evidence. |
| Local malware/AV scanning gate is active before parsing, or explicitly deferred by owner in the Gate B evidence report. | Pass | Owner accepted local scanning on 2026-05-22 and selected local/internal ClamAV `clamd` `INSTREAM` on 2026-05-26. Prerequisite issues #93, #94, #101, #102, #103 and #109 are closed. Issue #94 gates parser/estimate/preview/persistent-job access on Upload Safety Ledger accepted-source state when `require_upload_scan` is enabled. Issue #93 adds the app-side `clamd` adapter and fail-closed verdict taxonomy. Issue #109 adds internal-only `clamd` runtime shape and metadata-only local runtime smoke evidence: isolated compose project, no real `.env*`, no `var/`, no live server and no user data; app image reached internal `clamd`; safe metadata reported `status=ok`, `scanner_version=ClamAV 1.4.4`, `signature_database_version=28010`, `eicar_verdict=infected`. Current issue #95 local verification on branch `codex/issue-95-malware-gate-b-evidence`, working tree based on commit `5845842`, passed focused scanner/upload/runtime/deployment tests, full unittest, compileall and predeploy. Public malware scanning services do not receive user documents by default. | Approved beta-server smoke remains a separate Gate B item. Broader upload hardening/quarantine, TTL/quarantine cleanup and real-file matrix remain separate Gate B blockers. | `PYTHONPATH=src python3 -m unittest tests.test_document_scanner tests.test_clamd_runtime tests.test_upload_safety_ledger tests.test_bot_translation_service tests.test_bot_runtime tests.test_server_deployment_config`: `Ran 210 tests in 9.647s`, `OK`; `PYTHONPATH=src python3 -m unittest discover -s tests`: `Ran 1099 tests in 21.211s`, `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src`: passed; `scripts/predeploy_check.sh`: `Ran 64 tests`, `OK`, lint passed, CLI smoke/shell syntax/documentation check/compile/diff hygiene passed. | No for this metadata-only local/synthetic evidence. Yes for production deployment, live/beta server operations, real `.env*`, runtime `var/`, real user data, external scanning, retention/runtime data behavior, public scanner exposure or changing fail-closed beta policy. | Keep scanner behavior in release regression checks. Do not treat this pass as full Gate B or free-beta readiness. |
| TTL cleanup is active for sources, finals, partials and quarantine. | Blocked | Retention defaults are proposed in `docs/restart/upload-safety-and-retention.md`; `docs/DECISIONS.md` marks baseline as Proposed; Gate B item is unchecked. | No idempotent cleanup/delete verification, no evidence for source/final/partial/quarantine object lifecycle. | Needed: retention/delete tests and release report; avoid real user data unless approved. | Yes; this is user-data handling/destructive-adjacent. | Follow-up: TTL cleanup/delete verification issue. |
| Real TXT/DOCX/EPUB matrix is executed and stored as a release artifact. | Blocked | Matrix template exists in `docs/restart/real-file-test-matrix.md`; Gate B item is unchecked. Issue #71 approved public-domain/permissive-license corpus policy. | No corpus manifest, no execution report, no artifact links, no pass/fail table. | Needed: fixture manifest with source/license URL and rights basis, commands, metadata-only artifact summary by default, release report. | No for public-domain/permissive-license metadata-only corpus policy; yes for raw source/output retention in git or use of private/runtime data. | Follow-up: real-file TXT/DOCX/EPUB matrix issue. |
| Cancel/resume/restart scenarios pass. | Blocked | Issue #30 PRs #36-#39 reduced one focused cancel/provider/admin reliability risk; docs state this does not complete Gate B. | No stored release evidence for cancel/resume/restart matrix across bot/worker/server restarts. | Needed: real-file or integration-style scenario report. | Usually no for synthetic/local tests; yes if using beta server/user data. | Follow-up: cancel/resume/restart evidence issue. |
| Bot restart does not make existing jobs invisible. | Blocked | Backend as source of truth is an active decision in `docs/DECISIONS.md`; bot state is adapter-only. | No release artifact proving jobs remain visible after bot restart. | Needed: bot restart scenario covering history/My Books/status. | Yes if performed on live/beta runtime data. | Follow-up: bot restart visibility evidence. |
| Provider failure creates diagnosable metadata and safe user messaging. | Blocked | PR #39 and issue #31 evidence are documented; unsafe model-output classification is active in `docs/DECISIONS.md`. | No full release artifact proving safe user messages and metadata across provider failure classes. | Needed: provider failure tests/report for timeout, auth/billing/rate-limit/unavailable/malformed and unsafe model output. | Yes for provider contract/user-facing diagnostics changes. | Follow-up: provider failure safe diagnostics issue. |
| Local EPUBCheck release validation passes for EPUB fixtures. | Blocked | Matrix requires EPUB validation; Gate B item is unchecked. Issue #71 approved local/offline EPUBCheck as the required Gate B validation tool. EPUBCheck is a release verification tool, not a production dependency; online EPUB validation services are not approved. Exploratory local EPUBCheck v5.3.0 run on 2026-05-17 worked as a tool check but selected EPUB fixtures failed validation. | `test_samples/sample_book.en.epub` failed with 3 errors: missing `dcterms:modified`, missing `nav`, undefined fragment identifier. `test_samples/russian_profile_regression.en-ru.epub` failed with 2 errors: missing `dcterms:modified`, missing `nav`. `artifacts/Amerika - Franz Kafka - EPUB.uk.quotes-fixed.epub` failed with 110 errors, primarily duplicate XHTML IDs and missing CSS resource `page.css`. | Needed: per-fixture EPUBCheck command/output summary and fixes or explicit beta triage for failing EPUB outputs. Errors block fixtures; warnings are recorded and triaged. | No for local/offline EPUBCheck as a release tool; yes to change tool policy, use online validators or add production dependencies. | Follow-up: EPUB validation issue. |
| DOCX openability/visual QA passes for DOCX fixtures. | Blocked | Matrix requires DOCX openability/visual notes; Gate B item is unchecked. Issue #71 approved local LibreOffice Writer as the Gate B reader/tool and "opens without repair/recovery prompt plus no blocker visual issues" as the pass threshold. | No approved fixture-level LibreOffice openability report or visual QA notes are recorded yet. | Needed: DOCX output artifacts and metadata-only visual QA notes using the approved threshold. | No for local LibreOffice metadata-only QA on authorized fixtures; yes for private/runtime data, online services or changing the pass/fail threshold. | Follow-up: DOCX openability/visual QA issue. |
| Backups visibility is visible in admin or a documented owner runbook report exists for the beta. | Blocked | Backup/restore scripts and restore runbook exist; Backups visibility is listed as a gap. Issue #71 approved a metadata-only owner runbook/report as the Gate B path, with admin UI deferred. | No owner report artifact exists yet. | Needed: latest backup/export timestamp, manifest verify result, restore rehearsal status and blockers in a metadata-only owner report. | No for metadata-only owner report using safe summaries; yes for backup/user-data surfaces or new admin UI. | Follow-up: Backups owner report issue. |
| Backup export passes `scripts/verify_backup_export.py`. | Blocked | `README.md`, `docs/QUALITY_GATES.md`, `docs/deployment/restore-runbook.md` document the command. | No manifest path or verification output artifact. | Needed: `python3 scripts/verify_backup_export.py <manifest>` output against approved backup. | Yes if using real beta/server backup data. | Follow-up: backup export verify issue. |
| Restore rehearsal passes from a backup artifact. | Blocked | Restore runbook exists and defines acceptance criteria. | No restore rehearsal artifact, no disposable-server/fresh-copy evidence. | Needed: verify backup, restore, server smoke, strict provider-key smoke where appropriate, status report. | Yes; backup/restore and runtime data are high-risk. | Follow-up: restore rehearsal issue. |
| No payment UI is exposed. | Pass | `README.md` Supported/Not Supported says payment UI is not supported for next beta; `docs/DECISIONS.md` says no payment UI in free closed beta and Gate C blocks payments. | Current runtime UI scan/server smoke not run in this task. | Needed before go/no-go: reviewer/server smoke confirms no payment UI route in beta flow. | Yes for any payment/pricing/UI change. | Keep paid work behind Gate C. |
| No paid job can be started. | Pass | `README.md`, `docs/DECISIONS.md` and `docs/restart/release-gates.md` separate free beta from Gate C paid beta; paid jobs are out of scope. | Runtime negative check not recorded in this task. | Needed before go/no-go: flow/server smoke confirms no paid-job path exposed. | Yes for any payment/job-start changes. | Keep paid jobs blocked until Gate C. |
| Logs/admin do not expose raw document text. | Pass | Issue #78 synthetic local review covered security telemetry, translation run artifacts, admin translation logs list/detail/API/download archive, live monitor, costs, operations, upload-safety admin views, provider health/validation/probe, audit, security summary and backup manifest/report helpers. The review found that admin translation-log archives could include raw run error details; focused bug [#117](https://github.com/ogirkoviylord/folioloom_main/issues/117) records the leak risk. The issue #78 fix now redacts translation run artifact event payloads and error fields before archive generation, and regression tests inspect archive contents for raw source/translated snippets, prompt text, API-key-like strings, provider key identifiers and traceback markers. | This is local synthetic evidence only. It does not inspect real `.env*`, live/runtime `var/`, real user documents, beta server logs or backup archives. Real-file TXT/DOCX/EPUB matrix and approved beta-server smoke remain separate Gate B blockers. | `PYTHONPATH=src python3 -m unittest tests.test_translation_run_logs tests.test_admin_routes tests.test_admin_translation_logs tests.test_security_telemetry tests.test_security_summary tests.test_admin_live_monitor tests.test_admin_costs tests.test_admin_operations tests.test_admin_upload_safety tests.test_admin_provider_health tests.test_admin_provider_validation tests.test_admin_provider_probe tests.test_admin_audit tests.test_backup_server_data`: `Ran 157 tests`, `OK`; `PYTHONPATH=src python3 -m unittest discover -s tests`: `Ran 1118 tests in 20.143s`, `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src`: passed; `python3 -m ruff check src/translator_service/translation_run_logs.py tests/test_translation_run_logs.py tests/test_admin_routes.py`: passed; `scripts/predeploy_check.sh`: `Ran 64 tests`, `OK`, lint/checks passed. | No for synthetic/local tests and metadata-only evidence. Yes for real runtime data inspection, beta/server logs, backup archives, real `.env*`, live `var/`, auth/admin exposure changes or new privacy/legal claims. | Keep redaction regression tests in release checks. Do not treat this pass as real-file matrix, beta-server smoke, backup/restore evidence or full Gate B readiness. |
| Beta safety telemetry stores safe budget metadata only: job/user ids, reservations, usage counts, costs, statuses and reason codes. | Pass | Checked in `docs/restart/release-gates.md`; `README.md` Beta Safety / Cost Guard explicitly excludes raw document text, prompts, translations and API keys. | Current telemetry inspection not run in this task. | Existing tests referenced: `tests/test_beta_safety.py`, `tests/test_beta_safety_store.py`. | Yes for telemetry schema or data-class changes. | Keep separate from paid billing ledger. |
| The common verification commands pass. | Pass | Issue #72 local verification on 2026-05-23 passed all three common commands from repo root on branch `codex/issue-72-gate-b-baseline`. This is local evidence only; current branch CI/run status remains Unknown because no PR/check evidence was inspected. | Server smoke, backup/restore, real-file, restart and other Gate B blockers remain missing. | `PYTHONPATH=src python3 -m unittest discover -s tests`: `Ran 1046 tests in 12.941s`, `OK (skipped=13)`; `PYTHONPATH=src python3 -m compileall src`: passed; `scripts/predeploy_check.sh`: passed, including server hardening tests `Ran 49 tests`, `OK`, lint `All checks passed!`, compile and diff hygiene. | No for local commands; yes if environment/data access is needed. | Re-run if code changes before go/no-go; do not treat this as server smoke or full Gate B completion. |
| `scripts/server_smoke_check.sh` passes on the beta server. | Blocked | Script is documented in `README.md`, `docs/QUALITY_GATES.md`, `docs/RELEASE_CHECKLIST.md` and restore runbook. | No approved beta-server smoke output. | Needed: `scripts/server_smoke_check.sh` output from approved target environment. | Yes; beta server access and operations require approval. | Follow-up: server smoke evidence issue. |

## 5. Passed Checks

Only the following are confirmed by repository evidence:

- Invite-only allowlist with SSH-tunneled admin editing/toggle is documented and
  checked in Gate B.
- Rights confirmation before full processing is documented and checked in Gate B.
- Free preview before full translation is checked in Gate B with PR/issue/local
  verification evidence for that item only.
- Per-user caps/job limits, global caps and admin kill switch are documented and
  checked in Gate B.
- Admin is intended to remain SSH-tunnel-only for closed beta.
- Payment UI and paid jobs are out of free-beta scope and blocked by Gate C.
- Beta safety telemetry is documented as safe metadata only and checked in Gate
  B.
- Release-wide logs/admin raw-text redaction evidence for issue #78 passed on
  2026-05-28 using synthetic local fixtures only. The fix redacts translation
  run artifact event payloads and error fields before admin log archive
  generation; regression tests inspect archive contents for raw
  source/translated snippets, prompt text, API-key-like strings, provider key
  identifiers and traceback markers. Focused bug #117 records the archive leak
  risk found during the review. This does not prove real-file matrix,
  beta-server smoke, backup/restore or full Gate B readiness.
- Local malware/AV scanning Gate B evidence for issue #95 passed on 2026-05-27:
  clean uploads require scanner plus ledger accepted-source state; infected,
  EICAR-equivalent, scanner timeout/unavailable/error/malformed response and
  unscanned/bypass paths fail closed before parser, preview/estimate,
  persistent job or worker access; local/internal `clamd` runtime smoke from
  issue #109 is metadata-only and does not use real `.env*`, `var/`, live server
  or user data. This checks only the malware/AV scanning item, not broader
  upload hardening, retention, server smoke or full Gate B readiness.
- Common verification commands passed in issue #72 local verification on
  2026-05-23: full unittest suite `Ran 1046 tests`, `OK (skipped=13)`,
  compileall passed, and `scripts/predeploy_check.sh` passed. This does not
  prove server smoke, backup/restore, real-file, restart or other Gate B
  blockers.

## 6. Blockers

These block free closed beta unless the owner explicitly approves deferral:

- TTL cleanup/delete verification for source/final/partial/quarantine objects.
- Authorized real-file TXT/DOCX/EPUB matrix and stored release report.
- Cancel/resume/restart, worker restart and bot restart release evidence.
- Scheduler/provider capacity release evidence.
- Provider failure safe diagnostics and user-message evidence.
- EPUB validation remains blocked: exploratory local EPUBCheck v5.3.0 ran on
  selected project EPUB fixtures on 2026-05-17 and found validation errors.
- DOCX openability/visual QA report.
- Admin Alerts MVP or approved owner-runbook alternative.
- Backups visibility in admin or documented owner runbook report.
- Backup export verification artifact.
- Restore rehearsal artifact.
- Approved beta-server smoke.

## 7. High / Critical Risks

High or Critical risks relevant to Gate B:

- R-003: unclear MVP readiness; Gate B not closed.
- R-005: cancel/resume/restart/worker recovery instability.
- R-008: brittle DOCX/EPUB/TXT real-file processing.
- R-010 and R-023: TTL cleanup/delete and retention policy not proven.
- R-011: background jobs and scheduler concurrency/race conditions.
- R-012 and R-020: runtime storage and user documents are high/critical user-data
  areas.
- R-014: logs/admin/error handling can leak raw text if unverified paths bypass
  redaction.
- R-016: admin auth/security and SSH-tunnel-only model must not be weakened.
- R-018: real `.env*` files exist and must not be read or edited.
- R-019 and R-025: external provider failures/costs require safe diagnostics and
  caps.
- R-026: deployment and rollback are Critical and require approval.
- R-027: backup/restore recoverability not evidenced.

## 8. Required Human Decisions

Recorded owner decisions:

- Free beta go/no-go threshold: complete all Gate B items before free closed
  beta. No implicit Gate B deferrals are approved.
- Beta success metrics: hard launch guardrails plus per-target-language
  translation-quality learning metrics. Existing Russian/Ukrainian automated
  quality scores are regression diagnostics, not universal success metrics for
  every target language.
- Real-file corpus and artifact retention policy: use public-domain or clearly
  permissive-licensed free-library/internet documents with recorded rights
  basis. Synthetic fixtures may live in repo; raw real source documents and
  translated outputs stay out of git by default.
- Retention/delete verification scope: synthetic test data by default, optional
  second pass only on an owner-approved disposable beta/runtime copy, and never
  on live beta/server data.
- Backup/restore evidence policy: backup exists to restore accepted beta work
  after server/runtime failure. Evidence may be collected only in
  owner-approved disposable/local/test/copy environments or an explicitly
  approved beta environment; live beta/server data requires exact-run owner
  approval. Release artifacts are metadata-only.
- CI policy: GitHub Actions Python checks are advisory for now; local gates
  unless visible PR/check evidence was inspected.
- DOCX visual QA threshold: local LibreOffice Writer is the approved Gate B
  reader/tool; pass means the fixture opens without repair/recovery prompt and
  has no blocker visual issues. Pixel-perfect source parity is not required.
- Alerts/Backups visibility approach: use a metadata-only owner runbook/report
  for Gate B now; defer new admin UI to a later follow-up.
- EPUB validation approach: use local/offline EPUBCheck as the required Gate B
  validation tool. Online EPUB validators are not approved. EPUBCheck is a
  release verification tool, not a production dependency. Errors block fixtures;
  warnings are recorded and triaged.
- Local malware/AV scanning direction: owner accepted adding local scanning on
  2026-05-22. Design is recorded in
  `docs/restart/local-malware-scanning-design.md`; #93 added the local `clamd`
  `INSTREAM` adapter, #109 added the internal-only `clamd` runtime shape, and
  issue #95 metadata-only local evidence on 2026-05-27 checks the malware/AV
  scanning Gate B item without claiming full Gate B readiness.

Remaining required human decisions:

- Any future Gate B deferral: no deferrals are currently approved; any later
  exception must name the owner approver and affected Gate B item.
- Any future change to fail-closed beta scanner behavior, external scanning,
  live/beta server operation, production deployment, real `.env*`, runtime
  `var/`, real user data or retention/runtime data behavior remains `TBD`
  until explicitly approved.

## 8.1 Issue #71 Owner Decision Register

GitHub issue
[#71](https://github.com/ogirkoviylord/folioloom_main/issues/71) asks agents to
record the owner decisions required before risky Gate B verification runs or
free closed beta readiness is claimed. This register records only explicit
decisions found in repository evidence. Where no explicit owner decision was
found, the status remains `TBD`; where evidence cannot be inspected from the
repository, it remains `Unknown`.

### Where decisions are missing

| Missing decision area | Where the gap appears | Why it blocks or constrains next work |
| --- | --- | --- |
| Server smoke environment | `docs/QUALITY_GATES.md`, `docs/RELEASE_CHECKLIST.md`, `docs/restart/release-gates.md` | `scripts/server_smoke_check.sh` requires approved target environment access and cannot be run as a routine local check. |

### Decisions the owner needs to make

| Decision area | Status | Recorded decision | Evidence / notes |
| --- | --- | --- | --- |
| Free beta go/no-go threshold | Approved | Complete all Gate B items before free closed beta. | Owner selected "complete Gate B first" during issue #71 implementation on 2026-05-16. |
| Beta success metrics | Approved | Hard guardrails: Gate B complete, `0` lost accepted jobs, `0` known raw text/prompt/translation/API key leaks, and `0` cap or kill-switch breaches. Learning metrics: per-target-language human feedback of `usable`, `not usable` or `needs review`, plus short reason tags. Russian/Ukrainian automated quality scores remain regression diagnostics, not universal launch metrics. | Owner approved this split during issue #71 implementation on 2026-05-17. |
| Real-file fixture corpus policy | Approved | Use public-domain or clearly permissive-licensed documents from free libraries and other internet sources. "Free to read online" alone is not sufficient; each fixture needs source/license URL and rights basis. Synthetic/generated fixtures may live in repo. Real source documents and translated outputs stay out of git by default; release artifacts default to metadata-only reports. | Owner approved free libraries/random documents as test material during issue #71 implementation on 2026-05-17, with rights-basis guardrail recorded. |
| Backup/restore evidence policy for beta | Approved | Backup exists to restore accepted beta work after server/runtime failure: jobs/work units, user-visible history, source/intermediate/partial/final files, admin/beta settings and privacy-safe operational metadata. Gate B evidence may be collected on owner-approved disposable local compose, disposable VPS/test server, disposable beta-runtime copy or explicitly approved beta environment. Live beta/server data requires exact-run owner approval. Passing evidence requires manifest verification, restore rehearsal, usable restored jobs/files/admin state, no raw text/secrets in evidence and SSH-tunnel-only admin. Release artifacts are metadata-only. | Owner approved this policy during issue #71 implementation on 2026-05-17. |
| Gate B deferrals | Approved | No implicit Gate B deferrals are approved. Any future exception requires explicit owner approval naming the affected Gate B item. | Owner selected "complete Gate B first" during issue #71 implementation on 2026-05-16. |
| Local malware/AV scanning evidence | Pass | Issue #95 metadata-only local evidence on 2026-05-27 checks the local malware/AV scanning Gate B item for clean, infected/EICAR-equivalent, timeout, unavailable/error/malformed response and unscanned paths. It relies on closed prerequisites #93, #94, #101, #102, #103 and #109, plus issue #109 local runtime smoke from an isolated compose/app-image run. | This is not a full Gate B, free beta, public production or deployment readiness claim. Approved beta-server smoke remains separate and Unknown. |
| DOCX visual QA threshold | Approved | Use local LibreOffice Writer as the Gate B DOCX reader/tool. A fixture passes only if it opens without repair/recovery prompt and has no blocker visual issues. Pixel-perfect source parity is not required for free closed beta; minor/major issues may be recorded as notes. | Owner approved the recommended option during issue #71 implementation on 2026-05-17. |
| Alerts/Backups visibility approach | Approved | Use a metadata-only owner runbook/report for Gate B now. The report must summarize provider, queue/worker, disk/storage, failed-job and backup/restore status without raw document text, prompts, translations, API keys, stack traces, backup archives or restored files. Admin UI expansion is deferred to a later follow-up. | Owner approved the owner report option during issue #71 implementation on 2026-05-17 and noted that admin UI should not require broad rewrites for each bot feature. |
| EPUB validation approach | Approved | Use local/offline EPUBCheck as the required Gate B validation tool. Online EPUB validation services are not approved. EPUBCheck is a release verification tool, not a production dependency. Errors block fixtures; warnings are recorded and triaged. | Owner approved the recommended option during issue #71 implementation on 2026-05-17. Exploratory local EPUBCheck v5.3.0 run found validation errors in selected EPUB fixtures, so Gate B EPUB validation remains blocked. |
| Dedicated Gate B common verification run | Pass | Issue #72 local verification on 2026-05-23 passed the dedicated Gate B common commands: full unittest suite `Ran 1046 tests in 12.941s`, `OK (skipped=13)`; compileall passed; `scripts/predeploy_check.sh` passed, including server hardening tests `Ran 49 tests`, `OK`, lint `All checks passed!`, compile and diff hygiene. | Local evidence only; CI status remains Unknown unless visible PR/check evidence is inspected. |
| Beta-server smoke status | Unknown | Unknown: no approved beta-server smoke output is recorded. | Server smoke requires approved target environment access. |

## 9. Verification Commands

Common commands before Gate B go/no-go:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Issue #72 current local baseline, recorded 2026-05-23 from repo root:

| Command | Result | Evidence summary |
| --- | --- | --- |
| `PYTHONPATH=src python3 -m unittest discover -s tests` | Pass | `Ran 1046 tests in 12.941s`; `OK (skipped=13)`. Output included expected test logging/security-event lines and best-effort mocked `database is locked` traces, but the command exited successfully. |
| `PYTHONPATH=src python3 -m compileall src` | Pass | Listed `src`, package directories and compiled `src/translator_service/document_sandbox_worker.py`; command exited successfully. |
| `scripts/predeploy_check.sh` | Pass | Server hardening tests `Ran 49 tests in 0.039s`, `OK`; lint `All checks passed!`; CLI smoke, shell syntax, documentation check, compile and diff hygiene completed; final line: `Predeploy check passed.` |

Issue #95 malware/AV evidence run, recorded 2026-05-27 from repo root on branch
`codex/issue-95-malware-gate-b-evidence`, working tree based on commit
`5845842`:

| Command | Result | Evidence summary |
| --- | --- | --- |
| `PYTHONPATH=src python3 -m unittest tests.test_document_scanner tests.test_clamd_runtime tests.test_upload_safety_ledger tests.test_bot_translation_service tests.test_bot_runtime tests.test_server_deployment_config` | Pass | `Ran 210 tests in 9.647s`; `OK`. Covers clean `clamd` `INSTREAM`, infected/EICAR-equivalent safe verdicts, unavailable, timeout, malformed and scanner-error fail-closed paths; bounded scanner backpressure; Upload Safety Ledger accepted-source gating; unscanned/bypass paths denied before parser/estimate/preview/persistent jobs/workers; bot runtime scanner config; internal-only `clamd` compose/server-smoke script wiring. |
| `PYTHONPATH=src python3 -m unittest discover -s tests` | Pass | `Ran 1099 tests in 21.211s`; `OK (skipped=13)`. Output included expected security-event logging, mocked best-effort `database is locked` traces, async slow-task diagnostics and one `ResourceWarning`; the command exited successfully. |
| `PYTHONPATH=src python3 -m compileall src` | Pass | Listed `src`, package directories and compiled successfully. |
| `scripts/predeploy_check.sh` | Pass | Compose config, server hardening tests `Ran 64 tests`, `OK`; lint `All checks passed!`; CLI smoke, shell syntax, documentation check, compile and diff hygiene completed; final line: `Predeploy check passed.` |

Issue #78 logs/admin raw-text redaction evidence run, recorded 2026-05-28 from
repo root on branch `codex/issue-78-gate-b-redaction`, working tree based on
commit `4019cc5`:

| Command | Result | Evidence summary |
| --- | --- | --- |
| `PYTHONPATH=src python3 -m unittest tests.test_translation_run_logs tests.test_admin_routes tests.test_admin_translation_logs tests.test_security_telemetry tests.test_security_summary tests.test_admin_live_monitor tests.test_admin_costs tests.test_admin_operations tests.test_admin_upload_safety tests.test_admin_provider_health tests.test_admin_provider_validation tests.test_admin_provider_probe tests.test_admin_audit tests.test_backup_server_data` | Pass | `Ran 157 tests in 5.269s`; `OK`. Covers synthetic redaction for security telemetry, translation run artifacts, admin logs list/detail/API/download archive, live/costs/operations/upload-safety admin views, provider health/validation/probe, audit, security summary and backup manifest/report helpers. |
| `PYTHONPATH=src python3 -m unittest discover -s tests` | Pass | `Ran 1118 tests in 20.143s`; `OK (skipped=13)`. Output included expected security-event logging, mocked best-effort `database is locked` traces and async slow-task diagnostics; the command exited successfully. |
| `PYTHONPATH=src python3 -m compileall src` | Pass | Listed `src`, package directories and compiled successfully. |
| `python3 -m ruff check src/translator_service/translation_run_logs.py tests/test_translation_run_logs.py tests/test_admin_routes.py` | Pass | `All checks passed!`. |
| `scripts/predeploy_check.sh` | Pass | Compose config, server hardening tests `Ran 64 tests`, `OK`; lint `All checks passed!`; CLI smoke, shell syntax, documentation check, compile and diff hygiene completed; final line: `Predeploy check passed.` |

Server smoke and backup/restore checks require approved environment/data access:

```bash
scripts/server_smoke_check.sh
python3 scripts/verify_backup_export.py <manifest>
```

Restore rehearsal must follow `docs/deployment/restore-runbook.md` on an
owner-approved disposable local compose environment, disposable VPS/test server,
disposable beta-runtime copy or explicitly approved beta environment. Running
backup/restore checks on live beta/server data requires explicit owner approval
for that exact run. Retention/delete verification may run on synthetic test data
by default and on an owner-approved disposable beta/runtime copy only; do not run
destructive restore, retention/delete or backup checks on live runtime/user data
without separate explicit human approval.

## 10. Recommended Follow-up Issues

1. Upload hardening/quarantine baseline.
   Acceptance: negative TXT/DOCX/EPUB fixtures reject/quarantine safely;
   quarantined files never reach workers; logs/admin show metadata only.

2. TTL cleanup/delete verification.
   Acceptance: source/final/partial/quarantine lifecycle is idempotent and
   tested on synthetic or approved data; deletion behavior is documented.

3. Real-file TXT/DOCX/EPUB matrix.
   Acceptance: approved fixture manifest, pass/fail report, safe artifact links,
   no raw text in logs/admin.

4. Cancel/resume/restart evidence.
   Acceptance: cancel, resume, bot restart and worker restart scenarios produce
   final/partial/safe failed state without lost accepted jobs.

5. Scheduler/provider capacity evidence.
   Acceptance: one key at capacity 1 remains serial; multiple free keys progress
   multiple documents; no duplicate work-unit claims.

6. Provider failure safe diagnostics.
   Acceptance: provider timeout/auth/billing/rate-limit/unavailable/malformed
   and unsafe-model-output scenarios produce safe user messages and metadata.

7. EPUB validation.
   Acceptance: EPUB fixtures pass local/offline EPUBCheck, or failures are
   triaged with explicit beta decision. Errors block fixtures by default;
   warnings are recorded and triaged. Current status: blocked after exploratory
   local EPUBCheck v5.3.0 found validation errors in selected EPUB fixtures on
   2026-05-17.

8. DOCX openability/visual QA.
   Acceptance: DOCX outputs open in approved reader/tool and manual QA notes
   capture structure/fidelity risks. Approved threshold: local LibreOffice
   Writer, opens without repair/recovery prompt and no blocker visual issues;
   pixel-perfect source parity is not required.

9. Alerts MVP.
   Acceptance: provider, queue/worker, disk, backup and failed-job signals are
   documented in a metadata-only owner report, with no secrets/raw text. New
   admin UI is deferred unless separately approved.

10. Backups visibility.
    Acceptance: latest backup/export/verify state is visible in admin or a
    documented metadata-only owner runbook report.

11. Backup export verify.
    Acceptance: approved backup manifest passes `scripts/verify_backup_export.py`
    and output summary is stored as evidence.

12. Restore rehearsal.
    Acceptance: approved restore rehearsal from backup artifact passes restore
    runbook acceptance criteria.

13. Server smoke evidence.
    Acceptance: approved beta target records `scripts/server_smoke_check.sh`
    output and confirms admin remains SSH-tunnel-only.

## 11. Final Summary

Already proven by repo evidence: core closed-beta foundation, checked Gate B
items for allowlist, rights confirmation, free preview, caps, kill switch and
safe beta telemetry; product scope remains free, Telegram-first, TXT/DOCX/EPUB,
no payments and SSH-tunnel-only admin.

Unknown: current CI run/pass status, approved beta-server smoke, real-file
matrix, restart survival, backup export, restore rehearsal and runtime proof
for no payment path.

Issue #71 decision register records owner-approved free beta threshold, beta
success metrics, real-file corpus/artifact policy, retention/delete
verification scope, backup/restore evidence policy, CI policy, DOCX visual QA
threshold, Alerts/Backups visibility approach and local/offline EPUBCheck
validation policy. Exploratory local EPUBCheck v5.3.0 evidence shows selected
EPUB fixtures currently fail validation, so EPUB validation is blocked.

Blocks beta: every unchecked Gate B item without evidence or explicit owner
deferral, especially TTL, real files, restart/capacity/provider failures,
EPUB/DOCX QA, alerts/backups, backup/restore and approved beta-server smoke.

Safest next step: create small GitHub issues for the blockers above, use only
synthetic or owner-approved fixtures/data, and collect approved
server/backup/restore evidence before any human go/no-go. Re-run local common
verification if code changes before go/no-go.
