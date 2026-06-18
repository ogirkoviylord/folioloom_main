# Risk Register

This is the active risk lookup. Full prior risk history is archived at `docs/archive/project-memory/RISK_REGISTER.full-before-trim.md`.

## How To Use

Do not read this entire file for every small task. Use it when work touches risky areas, release readiness, external integrations, runtime data, user data, provider behavior, payment/legal/security/deployment or broad architecture.

Owner Local Development Mode allows local reading and owner-chat discussion of raw text, secrets, `.env*`, provider payloads and diagnostics when relevant. The risk boundary is committing, publishing, external sharing, destructive operations or production-facing changes.

## Critical / High Risks

| ID | Risk | Severity | Current mitigation | Ask first? |
| --- | --- | --- | --- | --- |
| R-001 | Public production or paid readiness is claimed without evidence. | Critical | Gate B/C/D and release checklist remain required. | Yes for release/public/paid claims. |
| R-002 | Deployment/server changes expose admin, secrets or runtime state. | Critical | Admin remains SSH-tunnel-only; deploy/server work requires exact approval. | Yes. |
| R-003 | Payment/pricing work starts before Gate C. | Critical | Paid beta is blocked until payment ledger, idempotency, refunds/support and reconciliation exist. | Yes. |
| R-004 | Destructive operations delete runtime data, backups, user files or git work. | Critical | Require explicit owner approval, dry run where possible and rollback/restore path. | Yes. |
| R-005 | Secrets/raw text/provider bodies are committed or published by accident. | High | Local owner-chat access is allowed; external/committed publication requires explicit owner intent. | Yes for externalization. |
| R-006 | Scheduler/worker/database changes break recovery or accepted jobs. | High | Use focused architecture review, targeted tests and rollback/forward-fix plan. | Yes for schema/state changes. |
| R-007 | Glossary runtime evidence is over-trusted. | High | Latest automatic live smoke is no-go; local/fake evidence is not quality/release proof. | Yes for rollout/provider/cache claims. |
| R-008 | Cache reuse returns stale non-glossary or wrong-policy translations. | High | Glossary-injected enabled/test-path units bypass cache until approved cache-key work. | Yes for cache-key behavior. |
| R-009 | Real-file quality is assumed from synthetic/unit tests. | High | Gate B requires real-file matrix, DOCX visual QA and EPUB validation evidence. | Yes for release claims. |
| R-010 | Admin/auth/RBAC/security changes weaken owner-only access. | High | Require owner approval, targeted tests and reviewer pass. | Yes. |

## Active Product Risks

### Free closed beta gaps

Risk: The product feels close because many foundations exist, but Gate B evidence is incomplete.

Mitigation:

- Keep free beta as next milestone, not current status.
- Track TTL/delete, real-file matrix, DOCX/EPUB validation, restart/recovery, backup/restore, alerts and server smoke.
- Do not launch without owner go/no-go.

### Scope creep

Risk: Future formats, paid beta, public portal, API channels or model pickers can distract from closed beta reliability.

Mitigation:

- Future scope requires idea intake, owner approval and architecture review.
- Keep current beta scope TXT/DOCX/EPUB in Telegram.

## Active Technical Risks

### Runtime state and recovery

Risk: Persistent jobs/work units, scheduler leases, cancellation and partial/final outputs form a state machine. Small changes can affect recovery.

Mitigation:

- Use targeted scheduler/job/worker tests.
- Avoid parallel uncoordinated changes to scheduler and worker state.
- Treat migrations and retention as approval-gated.

### Provider behavior and cost

Risk: Provider failures, token overruns, invalid output and cost spikes can affect user experience and beta safety.

Mitigation:

- Keep provider runtime/key-pool/probe tests relevant.
- Preserve beta cost/cap guard.
- Require approval for meaningful live provider calls/spend.

### File fidelity

Risk: TXT/DOCX/EPUB output can be structurally valid but visually or semantically poor.

Mitigation:

- Separate structure, semantic quality and release readiness.
- Use real-file matrix and visual/openability checks.
- Keep raw QA evidence local unless explicitly published.

## Active Privacy / Legal / User Data Risks

### Local vs public raw data boundary

Risk: Owner-local raw text/secret access is useful, but the same material should not leak into public/committed artifacts.

Mitigation:

- Local owner chat can include raw material when useful.
- GitHub/docs/release/support/public artifacts require explicit owner intent for raw material.
- Prefer metadata summaries for committed artifacts unless asked otherwise.

### Rights and copyrighted material

Risk: Repeated rights prompts are noisy in local development, but public distribution still matters.

Mitigation:

- Assume owner-provided/local files are usable for local development/QA.
- Ask rights/publication questions only for external distribution, release artifacts, public docs or customer-facing flows.

## Active Operations Risks

### Deployment and server smoke

Risk: Server actions can change availability, secrets, runtime state or public exposure.

Mitigation:

- Require exact owner approval.
- Run `scripts/predeploy_check.sh` before deploy-related handoff.
- Server smoke only on approved environment.

### Backup and restore

Risk: Backups may exist without verified restore evidence.

Mitigation:

- Gate B needs restore rehearsal evidence.
- Destructive operations need backup/restore plan.

## Review Checklist

Before risky changes, check:

- Does it touch deploy/server, secrets/env, auth/security, payments, legal/privacy, database/state, retention, backups, runtime data or provider behavior?
- Is approval required for changing/publishing/destructive/external actions?
- What tests prove the behavior?
- What docs need update?
- What is the rollback or forward-fix path?

## Archive

Full old risk register: `docs/archive/project-memory/RISK_REGISTER.full-before-trim.md`.
