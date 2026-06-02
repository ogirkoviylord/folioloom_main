# Agent Skill Routing

## 1. Purpose

This document is the detailed reference for choosing AI-agent skills in this
repository. It supports, but does not replace, `AGENTS.md`.

Use it when a task is ambiguous, cross-role, risky, multi-step, or when an
agent needs to decide whether to use a repo-level skill or a specialized
global/plugin skill.

## 2. Authority Order

When instructions conflict, use this order:

1. `AGENTS.md`
2. `docs/QUALITY_GATES.md` and `docs/RISK_REGISTER.md` for safety and approval
3. repo-level `.agents/skills/*`
4. this routing reference
5. specialized global/plugin skills

Repo-level skills win over global skills with similar names inside this
repository. Specialized skills may provide domain knowledge, but they cannot
override project scope, approval gates, quality gates, or safety rules.

## 3. Skill Dispatch Contract

Before using a skill, changing files, running operations, or declaring work
complete, every agent must determine:

- Classification
- Risk level
- Primary agent role
- Primary repo-level skill
- Supporting skills, if any
- Required docs
- Human approval status
- Allowed action
- Verification plan

If a task matches multiple categories, use the highest-risk route. If any
matched route requires human approval and approval evidence is missing, stop at
analysis and propose a safe plan.

Owner-facing responses should be in Russian by default unless the owner
explicitly asks for another language. Keep code identifiers, commands, file
paths, tool names and quoted source text in their original language.

## 4. Valid Approval Evidence

Valid human approval evidence:

- explicit owner message in the current thread;
- owner comment in a GitHub issue or pull request;
- approved decision recorded in `docs/DECISIONS.md`;
- owner-approved checklist item in an active task, issue, or PR.

Not approval evidence:

- agent assumption;
- historical plan;
- draft spec;
- generated recommendation;
- "looks safe";
- old context that does not name the current task.

When approval is needed but missing, use `TBD` and set allowed action to
analysis only.

## 5. Classifications

| Classification | Meaning | Default action |
| --- | --- | --- |
| `docs-only` | Documentation or workflow text only, no runtime behavior change. | Edit docs if facts are evidenced. |
| `safe-small-task` | Low-risk scoped task outside high-risk areas. | Implement focused change. |
| `bugfix` | Fix incorrect behavior in an existing scoped area. | Reproduce or inspect, then focused fix. |
| `feature` | New behavior or user-visible capability. | Require issue/scope; escalate if risky. |
| `spike / discovery` | Research, design, intake, or uncertainty reduction. | Analyze; do not implement. |
| `risky task` | Touches high-risk areas, cross-component contracts, user data, or release gates. | Architecture review; stop without approval. |
| `release-related task` | Beta, deploy, rollback, production, or go/no-go decision. | Release readiness; deploy only through the owner-approved agent-executed deploy rule; never self-approve release. |

## 6. Primary Routing Table

| Task signal | Primary role | Primary skill | Required docs |
| --- | --- | --- | --- |
| New product, technical, UX, format, pricing, workflow, or release idea | Idea Intake | `idea-intake` | `PROJECT_BRIEF`, `ROADMAP`, `DECISIONS`, `HANDOFF`, `RISK_REGISTER`, `QUALITY_GATES`, `CONTEXT_MAP` |
| Accepted large goal, epic, bug cluster, or idea needing issues | Orchestrator | `task-breakdown` | `HANDOFF`, `ROADMAP`, `DECISIONS`, `CONTEXT_MAP`, `RISK_REGISTER`, `QUALITY_GATES` |
| Risky change, new integration, new file format, database/auth/security/privacy/payment/deployment change, or cross-component contract | Architect | `architecture-review` | `PROJECT_BRIEF`, `CONTEXT_MAP`, `DECISIONS`, `HANDOFF`, `RISK_REGISTER`, `QUALITY_GATES` |
| One approved issue or one explicit scoped small task | Implementer | `implementation` | `HANDOFF`, `CONTEXT_MAP`, `DECISIONS`, `QUALITY_GATES`, issue/task, related tests |
| Pull request, diff, or review request | Reviewer | `pr-review` | `QUALITY_GATES`, `RISK_REGISTER`, `DECISIONS`, issue/task, PR diff |
| Docs drift after verified code/product/risk/decision change | Scribe | `docs-sync` | `HANDOFF`, `DECISIONS`, `ROADMAP`, `RISK_REGISTER`, `QUALITY_GATES`, `RELEASE_CHECKLIST`, PR summary/diff |
| Beta, launch, deploy, rollback, production change, or go/no-go decision | Release Readiness | `release-readiness` | `HANDOFF`, `ROADMAP`, `DECISIONS`, `QUALITY_GATES`, `RISK_REGISTER`, `RELEASE_CHECKLIST` |

## 7. Agent State Machine

Default flow:

```text
new idea
-> idea-intake
-> task-breakdown if accepted and large
-> architecture-review if risky or cross-component
-> implementation when ready
-> pr-review after diff/PR
-> docs-sync if verified facts changed
-> release-readiness before beta/deploy/release decisions
```

Transitions may move backward. For example, Reviewer can send a task back to
Implementer, and Architect can send a large or risky task back to Orchestrator
for splitting.

## 8. Definition Of Ready For Implementation

Implementer may start only when the task has:

- clear GitHub issue or explicit scoped task;
- acceptance criteria;
- verification plan;
- risk classification;
- approval status;
- likely touched areas;
- out-of-scope list.

If any item is missing, Implementer should stop at analysis and propose the
missing issue/task clarification.

## 9. Stop List

Stop at analysis without explicit approval if a task touches:

- secrets, real `.env*`, keys, tokens, passwords, or secret storage;
- deployment, Docker, server scripts, production operations, bind addresses, or
  public admin exposure;
- payments, pricing, billing, refunds, paid jobs, payment UI, or payment
  provider policy;
- auth, security, RBAC, sessions, admin access, security telemetry, or
  redaction boundaries;
- legal, privacy, AUP, refund, support text, or user-data handling;
- database schema/state, migrations, scheduler/job/work-unit state, retention,
  TTL, backups, restore, runtime `var/`, or destructive operations;
- new production dependencies;
- scope expansion beyond Telegram-first closed beta, TXT/DOCX/EPUB, or the
  approved MVP;
- production-ready or release-ready claims.

## 10. Supporting Skill Selection Rules

Specialized skills are helpers, not workflow owners.

Rules:

- Use exactly one primary repo-level skill for the task route.
- Use 0-2 supporting skills by default.
- Use more than 2 supporting skills only for explicit planning, research,
  review, or architecture tasks where broad domain coverage is the deliverable.
- Do not use a supporting skill just because it exists.
- Do not let a supporting skill expand the task beyond the issue/scope.
- Supporting skills may inform analysis, but project gates decide whether action
  is allowed.
- If a supporting skill points toward payments, deployment, auth/security,
  legal/privacy, user data, database/state, new dependencies, or product-scope
  expansion, stop at the matching approval gate before implementation.

## 11. Skill Domain Catalog

Use this catalog after choosing the primary repo-level skill. Pick the smallest
set of supporting skills that directly matches the task signal.

| Domain | Use when the task mentions | Supporting skills | Guardrail |
| --- | --- | --- | --- |
| GitHub / PR / CI | GitHub issues, PRs, review comments, failing checks, CI status, branch publishing | `github:*` | Do not push or merge to `main`; do not claim CI passed without visible evidence. |
| Debugging / QA | failing tests, bug reproduction, regression, missing tests, QA coverage, test design | `superpowers:systematic-debugging`, `superpowers:test-driven-development`, `senior-qa`, `code-reviewer` | Follow `docs/QUALITY_GATES.md`; do not broaden a focused bugfix. |
| Security / Privacy | auth, RBAC, secrets, redaction, upload safety, threat model, vulnerability, unsafe logs/admin data | `codex-security:*`, `senior-security`, `file-uploads` | High/critical security, privacy and user-data areas stop without approval. |
| Product / Market | ICP, user research, product idea, positioning, launch, roadmap, customer discovery, competitors | `market-research`, `customer-research`, `jobs-to-be-done`, `persona-mapping`, `competitor-analysis`, `go-to-market`, `launch-strategy` | Analysis only until the idea is accepted and scoped. |
| Pricing / Business | pricing, packaging, willingness to pay, unit economics, paid beta, monetization, financial model | `pricing-strategy`, `pricing-unit-economics`, `willingness-to-pay`, `startup-financial-modeling`, `business-model-canvas`, `business-plan` | Payment/pricing gates still block implementation and public claims. |
| AI / Prompt / RAG / Eval | prompts, model outputs, LLM costs, eval rubrics, RAG, embeddings, prompt registry, model routing | `senior-prompt-engineer`, `advanced-evaluation`, `rag-architect`, `prompt-governance`, `llm-cost-optimizer` | Do not change provider/user-data behavior without approval and tests. |
| Frontend / Browser / Design | local UI, localhost/browser checks, frontend app, component UI, Figma, visual QA | `browser:browser`, `build-web-apps:*`, `figma:*` | Admin/auth/public exposure gates still apply; do not create public frontend scope unless approved. |
| Docs / Office Artifacts | DOCX, Word, spreadsheets, CSV/XLSX, slides, PPTX, generated artifacts | `documents:documents`, `spreadsheets:Spreadsheets`, `presentations:Presentations` | No invented facts, raw document text leaks, or release/readiness claims. |
| Infra / Cloud / Deploy | Cloudflare, Workers, Durable Objects, uploads/storage architecture, deployment idea | `cloudflare:*`, `file-uploads` | Deployment, production dependencies and runtime/user-data changes need approval. |
| Payments | Stripe, payment provider, checkout, refunds, billing, subscriptions | `stripe:*` | Analysis only unless Gate C scope and owner approval exist. |
| Media / Images | generated bitmap images, mockups, screenshots, visual assets | `imagegen`, browser/Figma skills when relevant | Use only when requested or when a visual artifact is part of the task. |
| OpenAI Products | OpenAI API, models, Responses API, tool usage, official docs | `openai-docs` | Prefer official OpenAI docs; do not change provider contracts without approval. |
| Internationalization | localization, translations, RTL, locale files, hardcoded strings | `i18n-localization` | Preserve existing product scope and safe user messaging. |
| Data Quality | CSV/data audit, anomaly checks, profiling, validation | `data-quality-auditor`, `spreadsheets:Spreadsheets` | Avoid raw user-data exposure; use metadata or approved fixtures. |

## 12. Trigger Examples

| Task | Primary route | Supporting skills | Notes |
| --- | --- | --- | --- |
| "Fix this failing test" | `implementation` | `superpowers:systematic-debugging` if cause is unclear | Run targeted test and compileall for code changes. |
| "Review this PR" | `pr-review` | `code-reviewer`; add `codex-security:*` if security-sensitive files changed | Findings first; verify approval gates and tests. |
| "Plan FB2 support" | `idea-intake` -> `architecture-review` if accepted | file/security skills as analysis helpers | New format is out of current MVP and needs approval. |
| "Pricing for paid beta" | `idea-intake` or `architecture-review` | `pricing-strategy`, `willingness-to-pay` | Analysis only; payment/pricing implementation remains gated. |
| "Open localhost and check UI" | depends on task, often `implementation` or `pr-review` | `browser:browser` | Use browser for verification, not as workflow owner. |
| "Create an XLSX report" | `implementation` or `docs-sync` depending on task | `spreadsheets:Spreadsheets` | Do not invent facts; record source evidence. |
| "Threat model upload scanning" | `architecture-review` | `codex-security:threat-model`, `file-uploads` | Security/privacy/user-data gates apply. |
| "Optimize LLM cost" | `idea-intake` or `architecture-review` | `llm-cost-optimizer` | Do not change provider behavior without scoped issue/approval. |
| "Update docs after a merged fix" | `docs-sync` | none by default | Update only docs that changed facts require. |
| "Prepare beta go/no-go" | `release-readiness` | `pr-review` or security helpers if evidence requires | Do not self-approve release. Agent-executed deploys require exact owner approval, documented target/ref/command, predeploy evidence, rollback expectations and server smoke/status checks. |

## 13. Routing Receipt

Final task reports should include a short routing receipt:

```text
Routing:
- Classification:
- Primary skill:
- Supporting skills:
- Approval status:
- Verification:
```

For simple answers without file changes, this can be one concise sentence. For
changes, include it before the normal task report.
