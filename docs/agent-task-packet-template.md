# Agent Task Packet Template

Use this template when Hermes/Kanban work needs a bounded handoff to another
agent or model. The packet is a task-local context filter, not a new source of
truth and not a persistent wiki.

## When To Use

- Multi-model or council work.
- Broad owner request that needs routing before implementation.
- Review handoff where the reviewer should not scan the whole repository.
- Product, UX, QA or implementation work where the orchestrator must give a
  future model a narrow context window.

Do not use this for simple single-file fixes, direct questions, or tasks where
`AGENTS.md` plus touched files are enough.

## Source Rules

- Repository docs and code stay the source of truth.
- Use `Unknown` when repository evidence is missing.
- Use `TBD` when an owner decision is required.
- Search snippets are only routing hints. Open the source file before relying
  on a fact.
- Do not include raw secrets, raw provider bodies, raw document text, private
  diagnostics or long copyrighted excerpts in packets meant for external tools
  or public surfaces.

## Context Search

Start with `DOCUMENT_INDEX.md` for broad document routing. Then use
path-restricted `rg` searches over likely active docs before considering any
heavier search layer. Broaden the path only when the narrow search misses.

Example commands:

```bash
rg -n --glob '*.md' --glob '!docs/archive/**' --glob '!docs/superpowers/plans/**' \
  "Gate B|EPUBCheck|real-file|release matrix" \
  DOCUMENT_INDEX.md CURRENT_PROJECT_STATE.md docs/ROADMAP.md \
  docs/restart/release-gates.md docs/restart/real-file-test-matrix.md docs/QUALITY_GATES.md

rg -n --glob '*.md' --glob '!docs/archive/**' --glob '!docs/superpowers/plans/**' \
  "Hermes|Kanban|review fix|must-fix-for-coder|council" \
  AGENTS.md DOCUMENT_INDEX.md docs/agent-task-packet-template.md .agents
```

If the result set is noisy, narrow the query or open `DOCUMENT_INDEX.md` again.
Do not create a local LLM wiki or FTS index unless a later accepted task shows
that `DOCUMENT_INDEX.md` plus `rg` is not enough.

## Packet

```markdown
# Task Packet: <short title>

Status: Draft / Ready / Blocked / Complete
Created: YYYY-MM-DD
Owner: GPT-Orchestrator
Target model/agent: Codex / GPT-Critic / DeepSeek-Critic / MiMo-Critic / DeepSeek-Reviewer / MiMo-Reviewer / GLM-Worker / MiniMax-UX / TBD
Hermes card / issue: <link or Unknown>

## Goal
One concrete outcome.

## Classification
- Task type: docs-only / implementation / review / product-UX / QA / release / TBD
- Risk level: low / medium / high / TBD
- Primary skill: implementation / pr-review / idea-intake / translation-quality-review / TBD
- Approval status: not needed / approved / TBD

## Confirmed Facts
- Confirmed: ...

## Assumptions
- Assumption: ...

## Unknowns / TBD
- Unknown: ...
- TBD: ...

## Source Docs Opened
- `AGENTS.md` - why opened.
- `DOCUMENT_INDEX.md` - why opened.
- `docs/...` - why opened.

## Search Evidence
- Query: `...`
- Opened from results: `...`
- Ignored as stale/noisy: `...`

## Scope
- In scope: ...
- Out of scope: ...

## Approval Boundaries
- Stop before: deployment / server operation / payment / auth / database state /
  retention / provider spend / public text / dependency / MVP expansion / TBD.

## Relevant Files
- `path/to/file.py` - expected reason.

## Expected Output
- Proposal / critique / patch / review findings / QA report / synthesis.

## Verification
- Command/check: `...`
- Manual evidence: ...

## Model-Specific Instructions
- For GPT-Critic: red-team the GPT-Orchestrator proposal before external model
  critique. Focus on scope creep, weak assumptions, missing acceptance
  criteria, poor task-packet quality, approval gates, unverifiable claims and
  missing verification. Do not code and do not make final decisions.
- For critic/reviewer: classify findings as `owner-blocker`,
  `must-fix-for-coder`, `nice-to-have` or `ignore`.
- For critic/reviewer: use repo-level skills as analysis modes when the packet
  routes there. Use `architecture-review` criteria for risky or
  cross-component architecture/provider/auth/admin/DB/runtime work. Use
  `translation-quality-review` criteria for translation QA, glossary effects,
  language profiles, terminology, EPUB/DOCX/TXT outputs or pipeline
  regressions. Do not broaden into unrelated skills without packet evidence.
- For implementation worker: do not expand scope; return changed files, tests,
  residual risk and any `TBD` / `Unknown`.
- For UX/product reviewer: focus on user journey, next best action, confusing
  states and product fit; do not invent release status.

## Return Format
- Summary:
- Files or docs touched/reviewed:
- Findings or changes:
- Verification:
- Risks/follow-ups:
- Owner decisions needed:
```

## Five-Task Pilot

Before adding a wiki, FTS index or new search service, run five real Hermes
tasks with this packet format and record whether it reduced context reads.

For each task, record:

- task title;
- packet file or Hermes card;
- search queries used;
- source docs opened;
- whether another model received only the bounded packet;
- whether missing context caused rework;
- keep / revise / abandon decision.
