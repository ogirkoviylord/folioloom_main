# Quality Gates

Use the smallest verification that matches the change. Full pre-trim quality gate detail is archived at `docs/archive/agent-routing/QUALITY_GATES.full-before-trim.md`.

## General Gate

Every completed task should satisfy:

- scope is clear;
- diff is focused;
- no unrelated refactor;
- no invented facts;
- high-risk actions have approval when required;
- tests/checks are reported honestly;
- `Unknown` and `TBD` are used where appropriate;
- risks/follow-ups are stated.

Owner Local Development Mode allows local reading and owner-chat discussion of secrets, `.env*`, raw text, translations, provider payloads and runtime diagnostics when relevant. Do not commit, publish, externally send, destructively operate on or change these materials without explicit owner approval.

## Python Verification

Commands:

- Targeted unit tests: `PYTHONPATH=src python3 -m unittest tests.test_<module>`
- Full unit suite: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Compile check: `PYTHONPATH=src python3 -m compileall src`
- Local predeploy gate: `scripts/predeploy_check.sh`
- Targeted lint inside predeploy: `python3 -m ruff check <focused files>`

Recommended:

- Small localized code change: targeted tests + compile when practical.
- Shared behavior / worker / scheduler / admin / provider / bot / storage / file adapter change: broader relevant tests; full suite when risk warrants.
- Release/predeploy-related change: `scripts/predeploy_check.sh`.
- Docs-only: no code tests unless docs change behavior, commands, release claims or contracts.

Known:

- Repo-wide ruff debt exists and is not automatically a release blocker.
- Dedicated typecheck/format gates are `TBD`.
- GitHub Actions status is `Unknown` unless checked for the PR/run.

## Docs Gate

Docs updates must:

- avoid invented facts;
- link to evidence or mark `Unknown`;
- use `TBD` for owner decisions;
- not turn historical plans into current roadmap;
- not claim release/production/payment/legal readiness without evidence;
- preserve archive links when moving history out of active docs.

Docs-only changes usually need no code tests. State that explicitly.

## Review Gate

Review should check:

- blockers and correctness risks first;
- scope and acceptance criteria;
- tests run / missing tests;
- high-risk touched files;
- approval status for risky actions;
- docs impact;
- release/readiness claims;
- accidental publication/commit of raw private material.

Do not say "CI passed" unless CI evidence was actually checked.

## Risk Gate Summary

Ask before changing, publishing, deploying, destructively operating on or externalizing:

- deploy/server/production/public exposure;
- branch push or PR open/update unless the owner asked to make/publish a PR;
- merge/release/tag/direct `main` changes;
- secrets/env/key storage outside local read/debug/chat use;
- auth/RBAC/admin sessions/security telemetry/redaction boundaries;
- database schema/state, scheduler/job/work-unit state, retention, TTL, backups, restore;
- runtime `var/` destructive operations;
- payments/pricing/refunds/paid jobs/payment providers;
- public legal/privacy/AUP/support/refund text;
- meaningful live provider calls/spend;
- production dependencies;
- scope expansion beyond current MVP.

## Release Gate

Release/deploy/go-no-go work requires:

- owner approval;
- relevant release checklist reviewed;
- `scripts/predeploy_check.sh` evidence;
- server smoke/status only with approved environment access;
- rollback/restore expectations;
- Gate A/B/C/D status or explicit deferral;
- no production-ready claim without evidence.

## Area-Specific Notes

### Scheduler / Worker / State

Run targeted scheduler/job/worker tests. Schema/state changes need approval and rollback/forward-fix plan.

### Bot / User Flow

Run bot runtime/service/message tests relevant to the change. Preserve rights confirmation, beta allowlist, cost caps, kill switch and safe user messaging unless explicitly scoped.

### Provider Layer

Run provider runtime/key-pool/probe/client tests. Meaningful live calls need exact approval. Keep provider picker non-user-facing.

### Admin / Security

Run relevant admin/auth/security tests. Public exposure, auth/RBAC, secret storage and redaction changes need approval.

### Translation / File Adapters

Run format-adapter/translation/output-contract tests. For release-quality claims, unit tests are not enough; use real-file matrix and visual/validation evidence.

### Glossary Runtime

Latest automatic live smoke is no-go. Local/fake/provider-boundary evidence does not prove runtime rollout, quality or release readiness. Cache bypass remains active for glossary-injected enabled/test paths unless approved cache-key work changes it.
