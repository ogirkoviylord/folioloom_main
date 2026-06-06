# Admin Security, Safety, Audit, and Settings IA Review

## Scope

This document is the architecture-only recommendation for GitHub issue #344,
`Architecture review: Security, Safety, Audit, and Settings admin IA`.

No code, auth, RBAC, secrets, sessions, deployment, payment, legal/privacy, or
release-readiness behavior is approved by this document.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high.
- Primary agent role and repo-level skill: Architect Agent,
  `.agents/skills/architecture-review`.
- Supporting skills: Reviewer Agent / `.agents/skills/pr-review` after the
  docs-only diff is ready.
- Required docs read: `AGENTS.md`, `docs/PROJECT_BRIEF.md`,
  `docs/CONTEXT_MAP.md`, `docs/DECISIONS.md`, `docs/HANDOFF.md`,
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`.
- Code evidence inspected: `src/translator_service/admin/routes.py`,
  `src/translator_service/admin/views.py`,
  `src/translator_service/admin/auth.py`,
  `src/translator_service/admin/rbac.py`,
  `src/translator_service/admin/audit.py`.
- Human approval status: approved for architecture review by issue #344;
  missing for any implementation that changes auth, RBAC, sessions, secrets,
  admin access, security telemetry, redaction boundaries, public admin exposure,
  deployment, or legal/privacy text.
- Allowed action: analysis and docs-only architecture record.
- Verification plan for this PR: docs gate review plus `git diff --check`.

## Verdict

NEEDS SPLIT and NEEDS HUMAN APPROVAL for security/access implementation.

Security should become a hub over time, but the first implementation must be a
read-only IA shell that links existing safe surfaces. Do not merge, move, or
reimplement auth/RBAC/secrets/session behavior as part of navigation cleanup.

## Confirmed Facts

- `docs/PROJECT_BRIEF.md` says the admin console must remain SSH-tunnel-only,
  secrets must not appear in admin/logs, and raw document/translation text must
  stay confined to dedicated owner-only diagnostics.
- `docs/RISK_REGISTER.md` R-016 marks admin auth/security as high risk and says
  no bind/auth/RBAC changes without approval.
- `docs/RISK_REGISTER.md` R-017 says the permissions/RBAC model may be
  foundation-only and future named admins or public exposure are high risk.
- `docs/RISK_REGISTER.md` R-018 marks local real `.env*`/secret handling as
  critical.
- `docs/RISK_REGISTER.md` R-037 and R-038 protect owner-only raw diagnostics and
  internal reader boundaries from broadening into ordinary admin/user access.
- `src/translator_service/admin/views.py` currently exposes top-level primary
  nav items `Safety` (`/admin/upload-safety`) and `Settings`
  (`/admin/settings`), plus Advanced nav items `Audit` (`/admin/audit`) and
  `Security Events` (`/admin/security/events`).
- `src/translator_service/admin/routes.py` renders `/admin/security/events`
  from the shared activity store filtered to `ActivitySurface.SECURITY`.
- `src/translator_service/admin/routes.py` renders `/admin/upload-safety` from
  the upload-safety read model and detail routes.
- `src/translator_service/admin/routes.py` renders `/admin/settings` and
  `/admin/beta-controls` with the same `settings_body(...)`, including secret
  safety, beta allowlist, and beta safety controls.
- `src/translator_service/admin/auth.py` currently authenticates a single
  bootstrap owner password into an owner session with a signed cookie and CSRF
  token.
- `src/translator_service/admin/rbac.py` defines owner/operator/viewer roles
  and permissions, including `MANAGE_ADMINS`, but this review did not find a
  user-facing admin management UI.
- `src/translator_service/admin/audit.py` stores admin audit events with actor,
  role, action, target, outcome, reason, redacted metadata, and timestamp.
- The current `/admin/audit` route is an informational placeholder copy in
  `create_admin_router(...)`; audit events are written by many mutating admin
  routes, but this review did not find a full audit event table view in the
  current code.

## Assumptions

- The owner wants less confusion between `Security`, `Safety`, `Audit`, and
  `Settings`, not a broad security implementation in this issue.
- Existing admin pages remain server-rendered and protected by the current
  session/CSRF model unless a separate approved security task changes that.
- The first IA change should optimize owner navigation during closed-beta
  operations, not public-production hardening.

## TBD / Unknown

- TBD: owner-approved final labels for hub tabs, such as `Access`,
  `Security Events`, `Admin Audit`, `Upload Safety`, and `Config Safety`.
- TBD: whether the owner wants `Settings` to stay top-level long term or become
  a collection of owning pages.
- TBD: future admin account model, password rotation flow, named admins, and
  password reset/recovery process.
- Unknown: whether the currently defined operator/viewer roles are intended for
  near-term use or are only scaffolding.
- Unknown: current CI status for any future implementation PR until the PR
  checks page is inspected.

## Recommended IA

Use `Security` as a hub, but keep it read-only first.

Recommended hub structure:

- `Security -> Overview`: read-only cards linking to access status, security
  events, admin audit, upload safety, secret/config safety, and raw diagnostic
  guardrails.
- `Security -> Access`: future owner-approved admin access/password/session/RBAC
  controls. This tab should not exist as writable UI until a separate risky
  implementation is approved.
- `Security -> Security Events`: existing `/admin/security/events`, sourced
  from security-filtered activity events.
- `Security -> Admin Audit`: existing audit-log concept, focused on admin
  mutating actions, actor/role, outcome, reason, and redacted metadata.
- `Security -> Upload Safety`: link or embedded summary for the existing
  upload-safety page; keep full upload safety details in the upload-safety
  domain until a separate issue proves moving it preserves scanner/quarantine
  guardrails.
- `Security -> Config Safety`: link to existing secret/config safety summary
  currently rendered on Settings.

Keep `Settings` top-level for now, but reduce it over time to product/runtime
configuration that is not clearly owned by a more specific page. `Beta Controls`
can remain top-level during closed-beta work because allowlist, cost caps, and
kill switch visibility are operationally important guardrails.

## Audit vs Activity

`Admin Audit` should answer: who changed an admin-controlled setting or
provider/admin state, when, what target was affected, whether it succeeded, and
what redacted reason/metadata was recorded.

`Activity` should answer: what user/service/security events happened across the
product, including bot actions, button clicks, lifecycle events, and security
outcomes. It is an append-only event log and a source for contextual timelines.

Do not combine them into one raw table. They have different trust semantics:

- Audit is a governance/accountability ledger for admin-side mutations.
- Activity is product/service telemetry and context for user, trace, and
  security investigation.
- Security can link both, but it should not erase the distinction.

## Upload Safety Placement

`Upload Safety` belongs near Security conceptually, but it should remain a
first-class Safety page during closed-beta readiness work.

Recommended near-term shape:

- Keep primary nav `Safety` until upload hardening, malware scanning, TTL/delete,
  and real-file Gate B evidence are easier to find.
- Add a Security hub card/link to `Upload Safety` in a safe-small follow-up.
- Avoid moving or rewriting scanner/ledger/detail routes until a separate
  upload-safety implementation issue approves the behavior and tests.

## Settings Placement

Keep `Settings` top-level in the next small IA slice because it currently owns
multiple operational controls:

- secret/config safety;
- beta allowlist;
- beta safety controls.

Future split candidates:

- Move or link secret/config safety into `Security -> Config Safety`.
- Keep beta allowlist and beta safety under `Beta Controls`.
- Leave generic service settings under `Settings`.
- Put admin access/password controls under `Security -> Access` only after
  owner-approved auth/security implementation.

## Affected Components

- `src/translator_service/admin/views.py`: navigation labels, hub view, and
  links/cards for existing surfaces.
- `src/translator_service/admin/routes.py`: optional read-only Security hub
  route and optional audit table route; no auth/RBAC changes in the first slice.
- `src/translator_service/admin/audit.py`: evidence source for future Admin
  Audit table; behavior changes require focused tests.
- `src/translator_service/admin/auth.py`: future Access/password/session work
  only after explicit owner approval.
- `src/translator_service/admin/rbac.py`: future named-admin or role UI work
  only after explicit owner approval.
- `src/translator_service/admin/secrets.py` and
  `src/translator_service/admin/secret_safety.py`: config safety evidence only;
  do not expose secret values.
- `tests/test_admin_routes.py` and focused admin auth/audit tests for any
  future implementation.

## Follow-Up Task Classification

Safe-small-task candidates, no extra human approval if strictly read-only and
behavior-preserving:

- Add a read-only `Security` hub route with cards linking to existing
  `Security Events`, `Audit`, `Upload Safety`, `Settings`/config safety, and
  documented guardrails.
- Rename `Security Events` nav text or route title for clarity while preserving
  the existing route and filtered activity source.
- Add cross-links between `Security Events`, `Admin Audit`, and `Upload Safety`.
- Add an audit table view over existing redacted `SQLiteAdminAuditLog` events,
  if it is read-only and metadata remains redacted.

Medium-risk / Reviewer-required candidates:

- Move `Audit` under a `Security` hub while preserving old links or redirects.
- Move `Upload Safety` from primary nav to Security while preserving
  discoverability and upload-safety tests.
- Split `Settings` display into smaller existing-control pages without changing
  form actions, CSRF, allowlist behavior, beta safety behavior, or secret
  masking.

High-risk / explicit owner approval required:

- Any password change, password rotation, recovery, reset, or multi-admin UI.
- Any auth/session/cookie/CSRF/RBAC permission behavior change.
- Any secret storage, secret display, provider key handling, or redaction
  boundary change.
- Any public admin hardening, bind address, deployment, Docker, or `.env*`
  contract change.
- Any change to security telemetry semantics or raw diagnostic access.
- Any legal/privacy/support copy change.

## Risks

- Combining Audit and Activity too aggressively can blur admin accountability
  with product telemetry.
- Moving Safety under Security too early can hide upload/malware/retention Gate
  B evidence from the owner during beta readiness work.
- Settings currently contains state-changing beta allowlist and beta safety
  forms; moving those controls without tests can weaken cost caps, allowlist
  visibility, or kill-switch workflows.
- Access/password/RBAC work can weaken SSH-tunnel-only admin or create public
  admin assumptions if treated as UI cleanup.
- Any new hub copy can accidentally claim production security, public admin
  readiness, legal/privacy readiness, or release readiness.

## Required Tests For Future Implementation

For read-only IA shell work:

- Auth redirect tests for new hub/routes.
- `Cache-Control: no-store` assertions for admin pages.
- Navigation active-state tests.
- Link presence tests from hub to existing pages.
- Redaction assertions: no secrets, raw document text, prompt text, translated
  text, provider payloads, stack traces, or `.env*` values in hub/audit pages.
- Existing upload-safety, security-events, settings, and audit tests remain
  green.
- `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`
- `PYTHONPATH=src python3 -m compileall src`
- Targeted `ruff --select F,I` on changed Python files.
- `git diff --check`.

For high-risk access/auth work:

- Architecture review specific to the chosen auth/session/RBAC change.
- Explicit owner approval recorded in the issue or PR.
- Focused auth/session/CSRF/RBAC negative tests.
- Audit tests for all new admin-access mutations.
- Secret redaction tests if any secret/config surface is touched.
- Release/deployment review only if bind address, public exposure, Docker,
  server scripts, or env contracts are touched.

## Required Docs Updates For Future Implementation

- Update `docs/HANDOFF.md` only after verified behavior changes the admin IA or
  access/security contract.
- Update `docs/RISK_REGISTER.md` only if a human-approved security/auth/access
  decision changes the risk posture.
- Do not update release checklist or release gates unless the future task is
  explicitly release-related and has evidence.
- Do not add legal/privacy/security assurance copy without owner/counsel
  approval.

## Recommended Implementation Plan

1. Create one safe-small follow-up issue for a read-only Security hub that links
   existing surfaces and makes the Audit/Activity distinction visible.
2. Keep `Safety` and `Settings` top-level in that first slice.
3. Add focused route/view tests and redaction tests.
4. Review the first hub PR before any navigation moves.
5. Create separate follow-up issues for audit table rendering, settings split,
   and upload-safety placement.
6. Treat any Access/password/admin controls as a separate high-risk epic with
   owner approval, threat model, tests, rollback plan, and docs review.

## Suggested Implementer Prompt

Implement only the approved read-only Security hub from
`docs/admin-security-safety-audit-settings-ia-review.md`. Do not change auth,
RBAC, sessions, cookies, CSRF, secrets, provider keys, upload safety behavior,
settings form actions, deployment, legal/privacy copy, or release-readiness
docs. Add cards/links to existing Security Events, Admin Audit, Upload Safety,
Config Safety, and Access placeholder status. Add auth/no-store/nav/link and
redaction tests. Report CI as Unknown unless a visible PR/checks page is
inspected.
