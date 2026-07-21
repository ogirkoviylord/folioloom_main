# Release Checklist

This is the active go/no-go checklist for beta, deploy, rollback, public launch
or production-related decisions. Full prior checklist detail is archived at
`docs/archive/project-memory/RELEASE_CHECKLIST.full-before-trim.md`.

## Rules

- The owner makes the final GO / NO-GO decision.
- Agents may collect evidence and identify blockers; they do not approve release
  readiness by themselves.
- Documentation-only changes do not require code tests unless they change
  behavior, release claims, deployment process, safety boundaries or user-data
  handling.
- Deploys require exact owner approval for target, ref/commit and command.
- Server smoke/status checks require an approved target environment.

## Release Types

| Type | Current posture |
| --- | --- |
| Documentation-only | Allowed with evidence review; no code tests unless docs change behavior/claims. |
| Internal development | Allowed for local/PR work with focused verification. |
| Closed alpha / design partner | Current target direction; needs Gates 0-4 evidence. |
| Operational safety | Old Gate B carry-forward; needed before broader real-file operation. |
| Public beta | `TBD`; do not claim ready. |
| Paid beta | Future gated stage; do not claim ready. |
| Production | Future gated stage; do not claim ready without Gate D and owner approval. |

## Pre-Release Evidence

Before any beta/deploy/release decision, check:

- `docs/CAT_WORKFLOW_GATES.md` for current product/release gate model.
- `docs/HANDOFF.md` for current state.
- `docs/ROADMAP.md` for stage and scope.
- `docs/DECISIONS.md` for active boundaries.
- `docs/RISK_REGISTER.md` for high/critical risks.
- `docs/QUALITY_GATES.md` for required checks.
- `docs/restart/release-gates.md` when Gate A/B/C/D evidence is relevant.

Use archive files only when older release rationale or prior checklist detail is
needed.

## Code And Deploy Checks

Known commands:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Targeted checks may include:

```bash
PYTHONPATH=src python3 -m unittest tests.test_<module>
python3 -m ruff check <focused files>
scripts/server_smoke_check.sh
scripts/server_status.sh
```

Checklist:

- [ ] Focused tests for changed areas passed or missing checks are explained.
- [ ] Compile check passed when code changed, or omission is explained.
- [ ] `scripts/predeploy_check.sh` passed before deploy, or owner accepted the
  named missing check.
- [ ] No unexpected dependency changes.
- [ ] No secrets/raw private material committed or published.
- [ ] No high-risk area changed without approval.
- [ ] Exact deploy target/ref/command is approved when deployment is in scope.
- [ ] Rollback or forward-fix path is known.

## Product And Safety Checks

- [ ] Current scope remains within #813 CAT-like author workflow, Telegram harness role and TXT/DOCX/EPUB unless owner approved a scope change.
- [ ] Rights confirmation, beta allowlist, cost caps and kill switch are not
  weakened.
- [ ] User-facing errors do not expose provider internals, secrets or raw private
  material.
- [ ] Admin remains owner-only and not publicly exposed.
- [ ] Provider changes do not introduce unapproved live spend or hidden capacity
  behavior.
- [ ] Retention, delete, backup/restore and runtime-data behavior are not changed
  without approval.
- [ ] Payment, legal/privacy, support and public policy claims are not added
  without evidence and owner approval.

## Output

For release-readiness work, report:

1. Verdict: GO candidate, NO-GO, or Needs more verification.
2. Release type and target.
3. Evidence checked.
4. Blockers / `Unknown` / `TBD`.
5. Required owner approvals.
6. Rollback/forward-fix readiness.
7. Next safest action.
