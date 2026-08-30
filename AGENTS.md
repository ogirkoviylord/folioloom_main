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

## Current Product Direction

Canonical strategy issue: #813. Canonical gate doc: `docs/CAT_WORKFLOW_GATES.md`.

FolioLoom is now evaluated as a CAT-like author/rightsholder translation workbench for authorized TXT/DOCX/EPUB documents. Telegram remains a useful upload/test/delivery harness, but it is no longer the defining product surface or release compass.

Old Telegram-first Gate B/C is operational/payment infrastructure only. Do not treat old Gate B closure as product readiness, glossary quality proof, free beta readiness or paid beta readiness. Glossary/terminology control is a core quality prerequisite; manual/author-approved glossary controls are the MVP quality path until automatic glossary runtime has representative evidence.

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
  to make/publish a PR for the current task or the action is a Hermes/Kanban
  approved implementation/final PR gate covered below;
- merge, release, tag or direct changes to `main`;
- destructive deletes/resets, runtime data cleanup, retention/TTL behavior, backups/restore operations or database migrations;
- payment, pricing, billing, refund, paid-job, legal/privacy/AUP/support public text or public user-data policy changes;
- meaningful live provider calls/spend outside the standing-approved bounded
  DeepSeek test-smoke envelope below, or Telegram operations outside local/fake
  tests;
- adding production dependencies;
- publishing raw text/secrets/diagnostics outside the local owner workspace;
- expanding product scope beyond the owner-approved CAT-like author workflow, Telegram harness role, TXT/DOCX/EPUB format scope, or the current #813 gate model.

If approval is missing, stop at analysis for that specific risky action and propose a safe local plan.

## Standing Approval: Bounded DeepSeek Test Smokes

The owner pre-approves autonomous local DeepSeek smoke/probe runs for
Hermes/Codex tasks when every condition below holds. Do not ask for a separate
approval each time if the run stays inside this envelope.

- Scope is local development for this repository only.
- Use existing repo tests or bounded smoke/probe scripts; do not add a new
  live-spend path just to use this approval.
- Run local/fake/unit tests and dry preflight first when the script supports
  them.
- Limit live provider use to at most 6 calls and 60000 total reserved tokens
  per task.
- Use current configured `DEEPSEEK_*` environment and existing script defaults;
  do not change provider keys, base URL, model routing, capacity caps or cost
  controls under this standing approval.
- Store raw prompts, raw provider responses, source excerpts and diagnostics
  only in local untracked `outputs/` or `var/` paths.
- GitHub issues/PRs, committed docs, release notes, support/public text and
  owner-facing summaries must stay metadata-only unless the owner explicitly
  asks to publish raw material.
- Treat results as debugging/planning evidence. They do not prove translation
  quality, release readiness, runtime rollout readiness, cache-safety or
  production behavior by themselves.

Stop and ask for explicit owner approval before exceeding those caps, changing
provider configuration, adding new provider-spend scripts, operating Telegram
or servers, deploying, changing runtime/cache behavior, externalizing raw
material or making release/quality/legal/public claims.

## Translation QA Agent Guidance

For translation QA over FolioLoom outputs, diagnostics and owner-provided
before/after runs:

- Use `content_role.*` metadata and content-role shadow report diagnostics as
  evidence for classification, prioritization and uncertainty only. They are
  not behavior authority, scoring policy, pass/fail gate authority or permission
  to skip/alter output content.
- When the owner provides comparable before/after runs, compare them safely at
  the smallest useful metadata/output level and keep conclusions evidence-bound:
  confirmed, assumption, `Unknown` or `TBD`.
- Keep suspicious legal/archive/publisher boilerplate translated and included by
  default. Do not remove, preserve untranslated, down-rank, suppress or classify
  it as non-user content unless a later owner-approved behavior policy explicitly
  changes that rule.
- Never publish raw source text, translations, prompts, provider bodies, secrets,
  private diagnostic excerpts, private/local paths or long copyrighted excerpts
  in GitHub issues/PRs, committed docs, release artifacts, public/support
  surfaces or external tools.
- Distinguish local synthetic fixture/test work from owner-gated full-book,
  provider, Telegram, server or release-quality runs. Synthetic/local metadata
  evidence does not prove full-book translation quality, release readiness or
  production behavior.
- Route behavior changes, scoring/profile changes, gate/pass-fail policy and
  content-role authority decisions to the Slice H owner decision path. Do not
  smuggle those decisions into QA docs, tests or implementation tasks.

## Context Routing

Read the smallest useful context set. Do not load large history files by default.

| Task type | Read first | Add only if relevant |
| --- | --- | --- |
| Small bugfix / implementation | `AGENTS.md`, touched files, nearby tests | relevant `docs/QUALITY_GATES.md` section, exact issue/spec |
| Docs-only | `AGENTS.md`, target doc, evidence source | `docs/DECISIONS.md` if changing decisions; archive if checking history |
| Current state / handoff | `docs/CAT_WORKFLOW_GATES.md`, `docs/HANDOFF.md`, `CURRENT_PROJECT_STATE.md` | `docs/ROADMAP.md`, `docs/DECISIONS.md` |
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

- New ideas should be captured in GitHub Issues first. If durable repository
  context is useful, add a concise note to the relevant active doc. Do not add
  new ideas to `docs/superpowers/plans/`; that directory is a historical
  implementation-plan archive.
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

## Hermes / Kanban Workflow

Use Hermes/Kanban as a durable task graph, not as a reason to interrupt the
owner for every small issue.

`blocked` is only for true owner-blockers: human decision, missing access,
missing approval for a gated action, high-risk scope expansion, contradictory
requirements, unsafe security/privacy/auth/payment/deploy/DB/runtime-data issue,
or unresolved `Unknown` after disciplined investigation.

Do not use `blocked` for `review-required`, `needs owner eyes`, `final sign-off`,
missing tests, fixable review findings, nice-to-have findings, lint/type/format
issues, docs notes or ordinary re-review. Route those to coder fix-loop,
re-review and final PR gate instead.

- Done cards are historical records. Do not reopen completed cards for rework;
  create a new follow-up card instead.
- When fixing review findings, use the same worktree as the original
  implementation when appropriate.
- Do not block the owner for fixable work. Missing tests, changelog/docs notes,
  lint/format/import fixes, small in-scope regressions and handoff cleanup are
  agent follow-ups, not owner blockers.
- Block the owner only for human product decisions, missing access,
  approval-gated areas, high-risk scope changes, contradictory requirements or
  unresolved `Unknown` items after disciplined investigation.
- Reviewers must classify findings as `owner-blocker`, `must-fix-for-coder`,
  `nice-to-have` or `ignore`.
- For `must-fix-for-coder` findings, reviewers should create or specify a
  follow-up implementation card with exact changes, acceptance criteria and
  verification commands.
- Implementation cards should complete when the implementation phase is done
  and a reviewer child already exists. Use `review-required` block only when
  there is no reviewer child or a human decision is actually needed.
- In Hermes/Kanban, opening or updating a focused PR is pre-approved when the
  card is an approved implementation task or a final PR gate for an approved
  GitHub issue/task. Do not block the owner only for PR-open approval. The PR
  must stay within the approved scope, link the issue/task, include verification
  evidence and risks, and avoid raw private material.
- Merge remains owner-approved only. Still block before opening/updating a PR
  if it would include unapproved high-risk scope, deployment/server operations,
  DB migration/data cleanup, payment/legal/public-policy changes, raw private
  material publication, production dependency changes, or scope expansion.
- Council work must be explicit: GPT-Orchestrator proposal -> GPT-Critic
  self-opposition -> DeepSeek-Critic and MiMo-Critic independent critique when
  MiMo is in scope -> optional MiniMax-Critic independent critique ->
  GPT-Orchestrator synthesis -> owner approval if required -> implementation.
- GPT-Critic is an internal planning red-team for GPT-Orchestrator output. It
  does not code, does not make final decisions and does not replace DeepSeek or
  MiMo peer critique.
- MiniMax participates only through `minimax-critic` as an optional independent
  Council critic for product/technical trade-offs, user consequences,
  operational gaps and simpler alternatives. It never receives implementation
  or coder work, does not review its own work and is not a synthesis,
  implementation, review or merge gate. Record a failed/absent MiniMax response
  as `Unavailable` and continue with the available Council evidence. A specific
  owner request may require MiniMax to be attempted for one Council, without
  changing these role boundaries.
- For multi-model or council work, GPT-Orchestrator should prepare a bounded
  task packet using `docs/agent-task-packet-template.md`, `DOCUMENT_INDEX.md`
  and targeted `rg` searches before handing work to another model.
- Final owner-facing summaries should be written by GPT-Orchestrator and
  include what changed, what passed, what remains risky, what needs an owner
  decision and the next recommended action.

## Review Fix Loop

Preferred flow:

1. Implementer completes the implementation card with a clear handoff.
2. GPT-Reviewer, DeepSeek-Reviewer and/or MiMo-Reviewer review the same worktree.
3. If fixes are needed and they are inside approved scope, create a new
   `gpt-coder` follow-up card.
4. The follow-up card uses the same worktree as the original implementation
   unless isolation is safer.
5. After fixes, create or promote a dependent re-review card.
6. Ask the owner only for true blockers or final merge/release approval.

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
