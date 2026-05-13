# AGENTS.md

## Core rules

- Work carefully and make small, focused diffs.
- Do not change code unless the task explicitly asks for code changes.
- Do not invent features, architecture, tests, CI, deployment steps, production readiness, legal/privacy claims, or release status.
- Use `TBD` when a human decision is required.
- Use `Unknown` when repository evidence is missing.
- Clearly separate confirmed facts from assumptions.
- Do not weaken safety, security, privacy, legal, payment, deployment, auth, or user-data guardrails.
- Do not push directly to `main`.

## Routing rules

Before any task, read this file. Then route by task type:

- Current state or handoff: read `docs/HANDOFF.md`, then `docs/CONTEXT_MAP.md`.
- Product scope, MVP, audience, or success criteria: read `docs/PROJECT_BRIEF.md`, `docs/ROADMAP.md`, and `docs/DECISIONS.md`.
- Architecture, cross-component contracts, or risky changes: read `docs/DECISIONS.md`, `docs/RISK_REGISTER.md`, and `docs/CONTEXT_MAP.md`.
- Implementation or bugfix: read `docs/CONTEXT_MAP.md`, `docs/QUALITY_GATES.md`, the touched module, and nearby tests.
- Documentation work: read `docs/PROJECT_BRIEF.md`, `docs/CONTEXT_MAP.md`, `docs/DECISIONS.md`, and the relevant existing docs.
- Review work: read `docs/QUALITY_GATES.md`, `docs/RISK_REGISTER.md`, and the relevant task/context docs.
- Release, beta readiness, deploy, rollback, or production change: read `docs/RELEASE_CHECKLIST.md`, `docs/QUALITY_GATES.md`, `docs/RISK_REGISTER.md`, and `docs/DECISIONS.md`.
- Roadmap or issue breakdown: read `docs/ROADMAP.md`, `docs/HANDOFF.md`, and `docs/RISK_REGISTER.md`.

## Human approval gates

Do not change or operate on these areas without explicit human approval:

- secrets, real `.env*` files, keys, tokens, passwords, or secret storage;
- deployment, Docker, server scripts, production operations, bind addresses, or public admin exposure;
- payments, pricing, billing, refunds, paid jobs, payment UI, or payment/provider policy;
- auth, security, RBAC, sessions, admin access, security telemetry, or redaction boundaries;
- legal/privacy/AUP/refund/support text or user-data handling;
- database schema/state, migrations, scheduler/job/work-unit state, retention, TTL, backups, restore, runtime `var/`, or destructive operations;
- new production dependencies;
- expanding product scope beyond Telegram-first closed beta, TXT/DOCX/EPUB, or the approved MVP.

If approval is missing, stop at analysis and propose a safe plan. Never treat beta safety accounting as a paid billing ledger, and never call the project production-ready without Gate D evidence and human approval.

## PR-only workflow

- Work on a branch; never push or merge directly to `main`.
- Keep each change PR-sized: one goal, clear scope, focused files, relevant tests.
- For risky work, Orchestrator Agent splits the goal, Architect Agent reviews risk before implementation, Implementer Agent makes one small change, Reviewer Agent reviews before merge, and Scribe Agent updates docs after verification.
- Do not create release, deploy, paid beta, or production claims inside a PR unless the required checklist evidence and human approval are recorded.
- If CI is absent or Unknown, do not say "CI passed"; report local verification evidence instead.

## Reviewer Agent rules

- Start reviews with blockers, risks, missing evidence, and required human decisions.
- Check scope, diff, tests run, docs impact, high-risk files, approval status, and release gate impact.
- Verify no raw document text, prompts, translations, API keys, secrets, provider internals, stack traces, or unsafe user data appear in logs, admin views, telemetry, docs, or artifacts.
- Check that rights confirmation, beta allowlist, cost caps, kill switch, SSH-tunnel-only admin, and payment/public-production gates were not weakened.
- For docs-only changes, confirm facts are evidenced and `TBD`/`Unknown` are used honestly.
- For code changes, require focused tests and the relevant gates from `docs/QUALITY_GATES.md`; broader/shared changes need broader verification.

## Scribe Agent rules

- Update docs only when behavior, contracts, decisions, risks, release gates, stage, handoff, or verified facts changed.
- Keep docs concise and useful for the owner and future AI agents.
- Do not turn plans, old specs, or assumptions into confirmed facts.
- Do not claim CI, passing tests, release readiness, production readiness, upload/TTL readiness, restore readiness, legal/privacy readiness, or payment readiness without evidence.
- Preserve links between `docs/HANDOFF.md`, `docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/QUALITY_GATES.md`, `docs/RISK_REGISTER.md`, and `docs/RELEASE_CHECKLIST.md`.

## Standard terms

- safe task: low-risk, scoped work that avoids high-risk areas and release readiness claims.
- risky task: work touching high-risk areas, cross-component contracts, user-visible behavior, user data, operations, or release readiness.
- human approval: explicit owner approval before changing or operating on high-risk areas.
- quality gate: required checks, tests, documentation evidence, and review conditions for a task, PR, or release.
- release blocker: an unchecked gate item that blocks release unless explicitly deferred by the human owner.

## GitHub Issues workflow

- GitHub Issues are the source of truth for tasks, ideas, bugs, spikes, and implementation scope.
- Do not start implementation unless the task has a clear issue, explicit scope, acceptance criteria, and verification plan.
- If the issue is unclear, stop at analysis and propose clarifying edits to the issue instead of guessing.
- One issue should normally produce one focused PR.
- Large ideas must first go through idea intake, task breakdown, and architecture review if risky.
- Keep planning discussion in the issue or PR so future agents can reconstruct context without relying on chat history.

## Skills routing

Use repo-level skills when available:

- Use `idea-intake` for new product, technical, UX, format-support, pricing, workflow, or release ideas.
- Use `task-breakdown` for splitting large goals into small GitHub issues.
- Use `architecture-review` before risky changes, new integrations, new file formats, database changes, auth/security/privacy/payment changes, or cross-component contracts.
- Use `implementation` for one approved, scoped issue.
- Use `pr-review` for pull request or diff review.
- Use `docs-sync` after verified behavior, decision, risk, roadmap, or release-gate changes.
- Use `release-readiness` before beta, public launch, deploy, rollback, or production-related decisions.

If a needed skill is missing, do not invent the workflow silently. Propose the missing skill or proceed with the closest documented process.

## Task intake rule

Before changing files, classify the task as one of:

- docs-only;
- safe-small-task;
- bugfix;
- feature;
- spike / discovery;
- risky task;
- release-related task.

If the task is a new idea, do not implement immediately. First evaluate it through idea intake and determine whether it should be accepted now, added to the roadmap later, explored as a spike, or rejected for now.

## Verification

- Use `docs/QUALITY_GATES.md` as the source of truth for verification commands and required checks.
- Do not claim that tests, lint, typecheck, CI, release gates, or smoke checks passed unless there is actual evidence.
- If commands are missing, failing, or unavailable, report that honestly and explain what was or was not verified.



## Required output after every task

After making changes, report:

1. Summary
2. Files changed
3. Files inspected
4. Tests run, if any
5. Confirmed facts
6. TBD / Unknown items
7. Risks or follow-up tasks
