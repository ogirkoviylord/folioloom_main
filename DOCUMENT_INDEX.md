# Document Index

Use this index to find the right document without loading archives into the first context window.

## Bootstrap Docs

- `AGENTS.md` - operating mode, autonomy, approval boundaries, routing, skill dispatch, verification basics.
- `CURRENT_PROJECT_STATE.md` - compact factual project state and gaps.
- `docs/HANDOFF.md` - current focus, recent high-signal changes, open questions and next-agent notes.
- `docs/CONTEXT_MAP.md` - directory/doc routing and task routes.
- `docs/QUALITY_GATES.md` - verification commands and gates.

## Product / State

- `README.md` - main repository entry point and commands.
- `README.project.md` - project overview.
- `docs/CAT_WORKFLOW_GATES.md` - canonical CAT-like author workflow gate model; start here for strategy/release questions.
- `docs/GATE1_GLOSSARY_SOURCE_SEAM_AUDIT.md` - Council-backed source seam audit and conditional next technical rehearsal for manual glossary control.
- `docs/PROJECT_BRIEF.md` - product scope, audience, value, components and non-goals.
- `docs/ROADMAP.md` - current milestone, immediate/next/later work.
- `docs/DECISIONS.md` - active decisions and short rationale.

## Risk / Release

- `docs/RISK_REGISTER.md` - active risk lookup.
- `docs/RELEASE_CHECKLIST.md` - release/deploy/go-no-go checklist.
- `docs/restart/release-gates.md` - current gate checklists; old Gate A-D/B-C is superseded as primary release compass.
- `docs/restart/real-file-test-matrix.md` - real-file QA matrix.
- `docs/restart/upload-safety-and-retention.md` - upload safety, quarantine, malware scanning, TTL and retention rules.
- `docs/restart/folioloom-restart-spec.md` - restart spec and product boundary.

## Deployment / Operations

- `docs/deployment/admin-vps-runbook.md` - VPS/admin/tunnel deployment model.
- `docs/deployment/restore-runbook.md` - backup verification and restore rehearsal.
- `docs/deployment/server-beta.md` - historical/superseded note; use current runbooks first.
- `.env.server.example` - server env contract.
- `docker-compose.yml` - compose services and mounts.
- `scripts/predeploy_check.sh` - local predeploy gate.
- `scripts/server_smoke_check.sh` - server smoke gate.
- `scripts/backup_server_data.py` and `scripts/verify_backup_export.py` - backup tooling.

## GitHub Workflow

- `.github/ISSUE_TEMPLATE/agent-task.yml` - agent-ready scoped implementation task.
- `.github/ISSUE_TEMPLATE/bug-report.yml` - reproducible defect report.
- `.github/ISSUE_TEMPLATE/idea-intake.yml` - new product/technical/UX/workflow/release idea intake.
- `.github/PULL_REQUEST_TEMPLATE.md` - PR summary, tests and risk checklist.

## Agent / Multi-Model Workflow

- `docs/agent-task-packet-template.md` - bounded Hermes/multi-model task packet template, `rg`-first context search guidance and future model handoff format.

## Active Quality / Translation References

- `docs/superpowers/specs/translation-language-quality-methodology.md`
- `docs/superpowers/specs/russian-translation-profile.md`
- `docs/superpowers/specs/ukrainian-translation-profile.md`
- `docs/superpowers/specs/russian-mqm-eval-rubric.md`
- `docs/competitive/translation-competitor-reports.md`
- `docs/restart/real-file-test-matrix.md`

## Active Admin / Operations References

- `docs/admin-ux-provider-processing-glossary.md`
- `docs/superpowers/specs/2026-05-08-folioloom-admin-console-design.md`
- `docs/superpowers/specs/2026-05-31-beta-operations-console-redesign.md`
- `docs/superpowers/specs/2026-05-09-deepseek-balance-admin-design.md`

## Active Glossary References

Open only exact files relevant to the task. The old long inline glossary/spec catalog lives in `docs/archive/agent-routing/CONTEXT_MAP.full-before-trim.md`.

High-signal current references:

- `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`
- `docs/superpowers/specs/2026-06-12-runtime-glossary-integration-architecture.md`
- `docs/superpowers/specs/2026-06-14-glossary-runtime-rollout-design.md`
- `docs/superpowers/specs/2026-06-14-glossary-cache-key-design.md`
- `docs/superpowers/specs/2026-06-15-deepseek-pro-glossary-prep-before-telegram-battle-test.md`
- `docs/superpowers/specs/2026-06-17-prepared-glossary-candidate-quality-audit.md`
- `docs/superpowers/specs/2026-06-17-glossary-scanner-v2-decision.md`

## Historical / Archive Lookup

- `docs/archive/README.md` - archive map.
- `docs/archive/project-memory/HANDOFF.full-before-trim.md` - full old handoff and issue-by-issue history.
- `docs/archive/project-memory/DECISIONS.full-before-trim.md` - full old decision log and rationale.
- `docs/archive/project-memory/ROADMAP.full-before-trim.md` - full old roadmap and backlog.
- `docs/archive/project-memory/RISK_REGISTER.full-before-trim.md` - full old risk register.
- `docs/archive/project-memory/RELEASE_CHECKLIST.full-before-trim.md` - full old release checklist.
- `docs/archive/agent-routing/CONTEXT_MAP.full-before-trim.md` - full old context map and glossary/spec catalog.
- `docs/archive/agent-routing/AGENT_SKILL_ROUTING.full-before-trim.md` - full old skill dispatch tables.
- `docs/archive/repo-skills/` - old full repo-level skills.

## Rule

If a document is not needed to decide the current task, do not read it yet. Archive files preserve memory; they are not mandatory startup context.
