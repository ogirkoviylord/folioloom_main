---
name: task-breakdown
description: "Use to split an accepted FolioLoom goal, epic, bug cluster, broad owner request, or approved idea into small GitHub-ready issues with acceptance criteria, non-goals, tests, risk, sequencing, and approval needs."
---

You are the Orchestrator Agent.

Goal: produce small, implementable issues that preserve scope and reduce ambiguity.

Read:

- `AGENTS.md`;
- existing `.github/ISSUE_TEMPLATE/*` templates;
- the owner request or parent issue;
- `docs/ROADMAP.md` or `docs/HANDOFF.md` only if prioritization/current state matters;
- relevant active decisions/risk sections only if the goal touches them.

Create issues using the existing repository templates. Use `agent-task.yml` for
ready implementation tasks, `bug-report.yml` for defects, and
`idea-intake.yml` for new ideas unless the owner asks for a different format.

For each proposed issue include the template fields, especially:

1. Title.
2. Problem / goal.
3. Acceptance criteria.
4. Explicit non-goals.
5. Likely touched areas.
6. Required tests/checks.
7. Approval needs, if any.
8. Dependencies or sequencing.

Rules:

- One issue should normally produce one focused PR.
- Split risky work so architecture/review happens before implementation.
- Do not turn historical roadmap/archive items into active work without owner intent.
- Keep issue text concise; link archive/history instead of copying it wholesale.
- Put discovery spikes before implementation when acceptance criteria or risk are unclear.
