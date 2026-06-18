# Agent Skill Routing

Use skills to improve outcomes, not to perform ceremony. Full old routing tables and examples are archived at `docs/archive/agent-routing/AGENT_SKILL_ROUTING.full-before-trim.md`.

## Default Rule

- Use zero or one primary repo-level skill for routine tasks.
- Use supporting global/plugin skills only when they add concrete expertise, tool access or verification value.
- Do not load heavy docs just because a skill exists.
- If a task matches multiple risk levels, follow the highest-risk route for approval and verification.

## Primary Routes

| Signal | Primary skill | Minimal docs |
| --- | --- | --- |
| New idea/scope question | `idea-intake` | `AGENTS.md`, relevant brief/roadmap |
| Accepted large goal | `task-breakdown` | `AGENTS.md`, roadmap/current state |
| Risky/cross-component work | `architecture-review` | `AGENTS.md`, decisions, relevant risk/spec |
| One scoped task | `implementation` | `AGENTS.md`, issue/task, touched files, nearby tests |
| Diff/PR review | `pr-review` | `AGENTS.md`, issue/PR scope, diff, touched files/tests |
| Translation output QA | `translation-quality-review` | `AGENTS.md`, source/translation/output |
| Verified docs drift | `docs-sync` | `AGENTS.md`, changed files, target docs |
| Release/deploy/go-no-go | `release-readiness` | release checklist, gates, runbook |

## Supporting Skills

Use 0-2 supporting skills by default. Add more only when the task explicitly requires broad planning/research/review.

Examples:

- failing test with unclear cause: systematic debugging;
- security-sensitive diff: security review skill;
- frontend visual QA: browser/frontend skill;
- OpenAI API question: OpenAI docs skill;
- spreadsheet/report artifact: spreadsheet/document skill.

Supporting skills do not override project scope, owner-local mode, approval gates or active decisions.

## Context Budget

| Task | Budget posture |
| --- | --- |
| Tiny bugfix | Code/tests first; no handoff/roadmap unless needed. |
| Normal implementation | Issue/task scope + code/tests + relevant quality gate + exact spec if needed. |
| Docs-only | Target doc + evidence source. |
| Risky architecture | Decisions + relevant risk + relevant spec/code. |
| Release/deploy | Release checklist + runbook + gates. |
| Historical reconstruction | Archive lookup through `DOCUMENT_INDEX.md`. |

## Approval Posture

Owner Local Development Mode reduces local read/chat approvals. It does not remove ask-first gates for deployment, publication, destructive operations, payments/legal/public policy, production dependencies or meaningful live provider spend.

## GitHub Issues

When a GitHub issue exists, it is the primary scope contract. Skills should
extract acceptance criteria, non-goals and verification expectations from the
issue before implementation or review. If issue scope conflicts with active
docs or safety gates, stop and report the conflict instead of guessing.

## Final Receipt

Routine work can use a compact report. Risky/release work should include:

- classification;
- primary skill;
- approval status;
- verification.
