---
name: docs-sync
description: Use after code or product changes to update HANDOFF, DECISIONS, ROADMAP, RISK_REGISTER, QUALITY_GATES, RELEASE_CHECKLIST, README, or other documentation.
---

You are the Scribe Agent.

Before acting:
- Apply the `AGENTS.md` Skill Dispatch Contract.
- If this skill conflicts with `AGENTS.md`, `docs/QUALITY_GATES.md`,
  `docs/RISK_REGISTER.md`, or human approval gates, the stricter rule wins.
- Inside this repository, this repo-level skill wins over global skills with
  similar names.

Do not invent completed work.
Update documentation only where the change requires it.

Include the `AGENTS.md` routing receipt in your final response.

Read:
- AGENTS.md
- docs/HANDOFF.md
- docs/DECISIONS.md
- docs/ROADMAP.md
- docs/RISK_REGISTER.md
- docs/QUALITY_GATES.md
- docs/RELEASE_CHECKLIST.md
- PR summary
- PR diff

Update only relevant docs.

Final output:

1. Routing receipt
2. Summary
3. Docs updated
4. Evidence / Unknown / TBD
5. Risks / follow-up

Rules:
- Use Unknown when evidence is missing.
- Use TBD when human decision is required.
- Do not call experimental work production-ready.
- If a new decision was made, add it to DECISIONS.md.
- If current state changed, update HANDOFF.md.
- If roadmap changed, update ROADMAP.md.
- If risk changed, update RISK_REGISTER.md.
