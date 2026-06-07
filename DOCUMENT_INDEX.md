# Document Index

Этот индекс отделяет активные источники правды от historical implementation
plans. Если старый plan содержит unchecked tasks, это не значит, что он остается
roadmap: сначала сверяйся с `CURRENT_PROJECT_STATE.md` и docs under
`docs/restart/`.

## Active Source Of Truth

- `CURRENT_PROJECT_STATE.md` - фактическое состояние проекта на restart.
- `README.project.md` - актуальный project overview.
- `README.md` - синхронизированный entrypoint для репозитория.
- `AGENTS.md` - обязательные правила работы AI-агентов, approval gates and
  Skill Dispatch Contract.
- `docs/AGENT_SKILL_ROUTING.md` - detailed reference for selecting agent roles,
  repo-level skills, supporting skills, approval evidence and routing state.
- `.agents/skills/translation-quality-review/SKILL.md` - repo-level
  Translation QA Agent skill for reviewing translated documents, books,
  source/translation pairs and pipeline outputs. Use after applying the
  Skill Dispatch Contract; it is not a code PR review skill.
- `docs/restart/folioloom-restart-spec.md` - canonical restart-ТЗ.
- `docs/restart/release-gates.md` - stage gates A-D.
- `docs/restart/two-week-engineering-plan.md` - ближайший 2-week plan.
- `docs/restart/real-file-test-matrix.md` - real-file corpus/release matrix.
- `docs/restart/upload-safety-and-retention.md` - upload hardening, quarantine,
  local malware scanning, TTL and retention rules.

## Active Deployment Docs

- `docs/deployment/admin-vps-runbook.md` - current VPS/admin/tunnel deployment
  model for `api`, `bot`, `worker`, `postgres`, `redis`.
- `docs/deployment/restore-runbook.md` - backup verification and restore
  rehearsal.
- `docs/deployment/server-beta.md` - historical/superseded note only. Use the
  two runbooks above and `docs/restart/folioloom-restart-spec.md` instead.
- `.env.server.example` - current server env contract.
- `docker-compose.yml` - current compose services and runtime mounts.
- `scripts/predeploy_check.sh` - current local predeploy gate.
- `scripts/server_smoke_check.sh` - current server smoke gate.
- `scripts/backup_server_data.py` and `scripts/verify_backup_export.py` -
  backup and verification tooling.

## Active Admin / Operations References

- `docs/admin-ux-provider-processing-glossary.md` - issue #11 owner-facing
  glossary for provider keys, provider/runtime health, processing capacity,
  queue state and beta safety admin fields. Use before copy/layout changes.
- `docs/superpowers/specs/2026-05-08-folioloom-admin-console-design.md` -
  active reference, partially implemented. Immediate gaps: Alerts MVP and
  Backups visibility.
- `docs/superpowers/specs/2026-05-31-beta-operations-console-redesign.md` -
  owner-approved design direction for the before-free-closed-beta admin
  redesign: incident-first Beta Operations Console, Translation Failure Trace,
  safe evidence packet, provider/key incident clarity, overview triage,
  navigation cleanup and action semantics. The first implementation stack was
  merged by PR #160 and issues #145-#152 are closed; follow-up admin diagnostics
  and release-evidence surfaces need separate issues.
- `docs/superpowers/specs/2026-05-09-deepseek-balance-admin-design.md` -
  active reference for admin-visible DeepSeek account balance, safe refresh,
  alerts and key-source behavior.
- `docs/superpowers/plans/2026-05-09-deepseek-balance-admin.md` -
  implemented plan for DeepSeek balance display and admin/env key coexistence.
- `docs/superpowers/plans/2026-05-09-admin-practical-ops-roadmap.md` -
  partially historical. Many slices are implemented; use it only as context for
  Alerts MVP and Backups visibility.
- `docs/superpowers/plans/2026-05-09-admin-server-diagnostics-fix-plan.md` -
  historical diagnostic plan. The remaining lesson is shared scheduler/runtime
  state and loud smoke checks.

## Active Quality / Profile Docs

- `docs/superpowers/specs/translation-language-quality-methodology.md`
- `docs/competitive/translation-competitor-reports.md` - cumulative
  competitive QA evidence for book/document translation services. Use as
  context for future quality-gate or positioning work; it is not a product
  decision, release-readiness evidence or universal competitor benchmark.
- `docs/superpowers/specs/2026-06-01-internal-before-after-reader-design.md` -
  active owner-approved internal/dev design direction for a local before-after
  reader over TXT/DOCX/EPUB adapter blocks, with issue/PR status for the first
  TXT/generic/DOCX/EPUB slices, including the DOCX structure preview in issue
  #195, CLI format auto-detection in issue #197 and the owner-only internal
  admin UI slice in issue #199. Scope remains internal QA on
  synthetic/test/public-domain/permissive or owner-approved files, not a
  user-facing reader, publisher workspace, public route or production-readiness
  claim.
- `docs/superpowers/specs/2026-06-01-docx-internal-preview-renderer-spike.md` -
  active issue #183 Architect spike note. It recommends keeping DOCX on the
  semantic/block reader for now, using local LibreOffice only as a reference/QA
  path, and deferring `docx-preview`/Mammoth/LibreOffice runtime dependencies
  to separately approved prototype or implementation issues.
- `docs/superpowers/specs/2026-06-01-epub-internal-reader-rendering-spike.md` -
  active issue #184 Architect spike note. It recommends keeping EPUB on the
  semantic/block reader for now, using the issue #189 explicit-input local
  report, issue #191 sandboxed XHTML chapter preview and issue #193 limited
  CSS/raster resource inlining before any book-like reader dependency, and
  keeping EPUBCheck as validation/reference only.
- `docs/superpowers/specs/book-manuscript-translation-mvp.md` - proposed MVP
  contract for issue #165. It fixes the first `book_manuscript` bar as
  structure preservation plus clean translation across TXT/DOCX/EPUB, records
  future terminology/glossary/analytics/new-format/quality issues and does not
  claim Gate B or release readiness.
- `docs/superpowers/specs/2026-05-14-translation-modes-design.md` - active
  Architect design for GitHub issue #43. It defines explicit document/form and
  book/manuscript translation modes, Telegram flow placement, adapter-routing
  contract, tests/fixture plan and out-of-scope boundaries. It is design only;
  current implementation status lives in `docs/HANDOFF.md`, `docs/ROADMAP.md`
  and the linked GitHub issues.
- `docs/superpowers/specs/russian-translation-profile.md`
- `docs/superpowers/specs/russian-mqm-eval-rubric.md`
- `docs/superpowers/specs/ukrainian-translation-profile.md`
- `docs/superpowers/specs/2026-05-08-ukrainian-translation-profile-design.md`
- `docs/superpowers/specs/2026-05-08-txt-layout-safe-translation-design.md`
- `docs/restart/real-file-test-matrix.md`

## Active Backend / Safety References

- `docs/superpowers/specs/2026-05-08-production-scheduler-design.md`
- `docs/superpowers/specs/2026-05-08-api-channel-reliability-design.md`
- `docs/superpowers/specs/2026-05-08-user-activity-security-logging-design.md`
- `docs/restart/upload-safety-and-retention.md`
- `docs/superpowers/plans/2026-05-10-smart-concurrency-phase-1.md` -
  implemented smart scheduler fairness/capacity plan for beta-safe worker
  concurrency.
- `docs/superpowers/plans/2026-05-10-provider-channel-observability-phase-2.md`
  - implemented provider-channel observability and key scoring plan.
- `docs/superpowers/plans/2026-05-10-adaptive-provider-throttling-phase-3.md`
  - active implementation plan for adaptive provider throttling and circuit
  breaker behavior.
- `docs/superpowers/plans/2026-05-10-cost-aware-beta-safety-phase-4.md` -
  implemented operational beta safety guard: live admin kill switch,
  global/user cost caps, reservation-at-enqueue, idempotent work-unit usage and
  Admin Costs/Settings/Live visibility. Not a paid ledger or Telegram Stars/XTR
  implementation.
- `docs/superpowers/specs/2026-05-10-deepseek-key-management-design.md` -
  active design for the dedicated admin DeepSeek key management workflow: safe
  key viewing, add/edit/rotate/remove/test actions, validation visibility and
  runtime reload UX.
- `docs/superpowers/plans/2026-05-10-deepseek-key-management.md` -
  implemented plan for the dedicated DeepSeek Keys admin page.

## Paid-Beta Draft Docs

- `docs/superpowers/specs/2026-05-09-folioloom-pricing-v0.md` - paid-beta
  draft only, not an immediate launch plan. Paid beta is blocked until Telegram
  Stars/XTR invoice flow, persistent ledger, idempotency, refunds,
  `/paysupport`, reconciliation and support policy are implemented.

## Historical / Superseded Specs

- `docs/superpowers/specs/2026-05-03-deepseek-document-telegram-bot-design.md`
  - early architecture rationale. Sections describing prototype/in-memory state,
  broad channel expansion or paid-first roadmap are outdated.

## Historical / Superseded Implementation Plans

These documents are an implementation history archive. Do not treat them as the
current roadmap unless a current restart doc explicitly links back to a slice.

Implemented or mostly implemented foundation:

- `docs/superpowers/plans/2026-05-03-deepseek-document-telegram-bot.md`
- `docs/superpowers/plans/2026-05-06-document-structure-optimizer.md`
- `docs/superpowers/plans/2026-05-06-epub-quality-fixes.md`
- `docs/superpowers/plans/2026-05-07-automatic-translation-run-logs.md`
- `docs/superpowers/plans/2026-05-07-format-adapters-docx.md`
- `docs/superpowers/plans/2026-05-07-format-adapters-epub.md`
- `docs/superpowers/plans/2026-05-07-format-adapters-txt.md`
- `docs/superpowers/plans/2026-05-07-persistent-bot-wiring.md`
- `docs/superpowers/plans/2026-05-07-persistent-document-assembly.md`
- `docs/superpowers/plans/2026-05-07-persistent-docx-planner.md`
- `docs/superpowers/plans/2026-05-07-persistent-epub-planner.md`
- `docs/superpowers/plans/2026-05-07-persistent-stored-unit-execution.md`
- `docs/superpowers/plans/2026-05-07-translation-policy.md`
- `docs/superpowers/plans/2026-05-08-api-channel-reliability.md`
- `docs/superpowers/plans/2026-05-08-document-sandbox-v1.md`
- `docs/superpowers/plans/2026-05-08-durable-backend-beta.md`
- `docs/superpowers/plans/2026-05-08-epub-repair-pipeline.md`
- `docs/superpowers/plans/2026-05-08-epub-translation-parity-hardening.md`
- `docs/superpowers/plans/2026-05-08-folioloom-admin-console-mvp.md`
- `docs/superpowers/plans/2026-05-08-my-books-detail-ui.md`
- `docs/superpowers/plans/2026-05-08-postgres-scheduler-parity.md`
- `docs/superpowers/plans/2026-05-08-production-scheduler.md`
- `docs/superpowers/plans/2026-05-08-prompt-injection-defense.md`
- `docs/superpowers/plans/2026-05-08-russian-quality-v2.md`
- `docs/superpowers/plans/2026-05-08-txt-layout-safe-translation.md`
- `docs/superpowers/plans/2026-05-08-ukrainian-translation-profile.md`
- `docs/superpowers/plans/2026-05-08-user-activity-security-logging.md`

Historical context, not current roadmap:

- `docs/superpowers/plans/2026-05-06-reference-alignment-action-plan.md`

Partially active only through restart gaps:

- `docs/superpowers/plans/2026-05-09-admin-practical-ops-roadmap.md` - Alerts
  MVP and Backups visibility remain active gaps.
- `docs/superpowers/plans/2026-05-09-admin-server-diagnostics-fix-plan.md` -
  keep the scheduler/runtime consistency lesson.
