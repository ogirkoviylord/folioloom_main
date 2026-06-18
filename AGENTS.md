# AGENTS.md

## Core Rules

- Work carefully and make small, focused diffs.
- Do not change code unless the task explicitly asks for code changes.
- Do not invent features, architecture, tests, CI, deployment steps, production readiness, legal/privacy claims, payment status or release status.
- Use `TBD` when a human decision is required.
- Use `Unknown` when repository evidence is missing.
- Separate confirmed facts from assumptions.
- Do not push or merge directly to `main`.
- Respond to the owner in Russian by default unless explicitly asked otherwise; keep code, commands, file paths, tool names and quoted source text in their original language.

## Owner Local Development Mode

Default assumption in this repository: the current chat is an owner-operated local development workspace.

Allowed without extra confirmation when relevant to the task:

- read local project files, tests, fixtures, outputs, `var/`, artifacts, diagnostics and run logs;
- read real `.env*` files, keys, tokens, passwords, raw provider payloads, prompts, raw document text, translations and diagnostic files;
- quote or discuss that material in this owner chat;
- use owner-provided or local files for development, testing, debugging, translation QA and evaluation without repeatedly asking for rights confirmation.

This local permission does not allow publishing or committing private material. Do not put raw secrets, raw document text, raw provider bodies, private diagnostics or long copyrighted excerpts into GitHub issues/PRs, committed docs, release artifacts, public/support/customer surfaces or external services unless the owner explicitly asks for that exact action.

## Ask First

Ask for explicit owner confirmation before:

- deployment, server operations, production operations, bind-address changes or public admin exposure;
- pushing a branch or opening/updating a PR, unless the owner explicitly asked
  to make/publish a PR for the current task;
- merge, release, tag or direct changes to `main`;
- destructive deletes/resets, runtime data cleanup, retention/TTL behavior, backups/restore operations or database migrations;
- payment, pricing, billing, refund, paid-job, legal/privacy/AUP/support public text or public user-data policy changes;
- meaningful live provider calls/spend or Telegram operations outside local/fake tests;
- adding production dependencies;
- publishing raw text/secrets/diagnostics outside the local owner workspace;
- expanding MVP scope beyond Telegram-first closed beta and TXT/DOCX/EPUB.

If approval is missing, stop at analysis for that specific risky action and propose a safe local plan.

## Context Routing

Read the smallest useful context set. Do not load large history files by default.

| Task type | Read first | Add only if relevant |
| --- | --- | --- |
| Small bugfix / implementation | `AGENTS.md`, touched files, nearby tests | relevant `docs/QUALITY_GATES.md` section, exact issue/spec |
| Docs-only | `AGENTS.md`, target doc, evidence source | `docs/DECISIONS.md` if changing decisions; archive if checking history |
| Current state / handoff | `docs/HANDOFF.md`, `CURRENT_PROJECT_STATE.md` | `docs/ROADMAP.md`, `docs/DECISIONS.md` |
| Architecture / risky work | `AGENTS.md`, `docs/CONTEXT_MAP.md`, exact relevant decision/spec, relevant risk section | archive only for older rationale |
| Review | diff, touched files, nearby tests, relevant gates | full risk/release docs only for risky diffs |
| Release / deploy / rollback | `docs/RELEASE_CHECKLIST.md`, `docs/QUALITY_GATES.md`, exact deployment/release docs | `docs/RISK_REGISTER.md`, `docs/DECISIONS.md` |
| Historical lookup | `DOCUMENT_INDEX.md`, `docs/archive/README.md` | exact archived file |

## Skill Dispatch

Use skills to improve work, not to perform ceremony. Prefer zero or one primary repo-level skill. Add supporting global/plugin skills only when they provide concrete expertise, tool access or verification value.

Repo-level skills:

- `idea-intake`: new product, technical, UX, format, pricing, workflow or release idea.
- `task-breakdown`: splitting an accepted large goal into small issues.
- `architecture-review`: risky, cross-component, new-format, database, auth/security/privacy/payment/deployment/provider work.
- `implementation`: one explicit scoped task or issue.
- `pr-review`: pull request or diff review.
- `translation-quality-review`: translated document/book/output quality review.
- `docs-sync`: docs update after verified facts changed.
- `release-readiness`: beta, deploy, rollback, production or go/no-go work.

Detailed old routing tables are archived at `docs/archive/agent-routing/AGENT_SKILL_ROUTING.full-before-trim.md`.

## GitHub Issues Workflow

When a GitHub issue is present, treat it as the primary task scope.

- When creating issues, use the existing `.github/ISSUE_TEMPLATE/*` templates.
  Do not invent a new issue format unless the owner explicitly asks.
- Read the issue title/body and relevant owner comments before implementation or review.
- Extract acceptance criteria, explicit non-goals, likely touched areas and verification expectations.
- Do not expand scope beyond the issue unless the owner explicitly asks.
- If issue scope conflicts with active docs, code reality or safety gates, stop and name the conflict.
- One issue should normally produce one focused PR.
- Large or vague issues should be split before implementation.
- PR descriptions and final reports should say which acceptance criteria were satisfied and which remain `TBD` / `Unknown`.
- Do not copy long issue discussion into docs; update docs only when verified behavior, decision, risk, command or release state changed.

If no issue exists but the owner gives a clear scoped task in chat, that chat task is enough. If the task is broad, ambiguous or risky, propose issue-ready acceptance criteria before implementing.

## High-Risk Boundaries

Local reading/debugging is allowed under Owner Local Development Mode. Changing, publishing, deploying, externalizing or destructively operating on high-risk areas still needs approval.

High-risk areas:

- secrets/env/keys outside local read/debug/chat use;
- deployment, Docker, server scripts, production operations and public exposure;
- payments, pricing, refunds, paid jobs and payment-provider policy;
- auth, RBAC, admin sessions, secret storage, redaction boundaries and security telemetry;
- public legal/privacy/AUP/support/refund text;
- database schema/state, scheduler/job/work-unit state, retention, TTL, backups, restore and destructive operations;
- production dependencies and major scope expansion.

## Verification

- Small code change: run targeted tests and `PYTHONPATH=src python3 -m compileall src` when practical.
- Shared behavior, worker/scheduler/admin/provider/bot/storage/file-adapter changes: run broader relevant tests or explain why not.
- Docs-only: verify facts; code tests are usually unnecessary.
- Release/deploy: use `scripts/predeploy_check.sh`; server smoke only with owner approval.
- Never claim CI/tests/release gates passed without evidence.

## Final Response

For routine work:

1. Summary.
2. Files changed.
3. Tests/checks run.
4. Risks/follow-ups.

For risky/release work, include a concise routing receipt:

- classification;
- primary skill;
- approval status;
- verification.
