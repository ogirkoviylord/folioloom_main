# Decisions

This file contains active project decisions in summary-first form. Full historical decision detail is archived at `docs/archive/project-memory/DECISIONS.full-before-trim.md`.

## Status Labels

- Active: current decision, agents should follow it.
- Superseded: kept for history only; do not follow by default.
- Deferred: accepted direction, not approved for implementation now.
- Proposed: not approved yet.
- TBD: owner/human decision needed.
- Unknown: repository evidence missing.

## Active Product Decisions

### Free closed beta before paid/public launch

- Status: Active.
- Summary: The next meaningful milestone is free closed beta, not paid beta or public production.
- Rationale: The technical foundation is strong enough for trusted-user learning, but real-file quality, TTL/delete, restore, server smoke, alerts, support/legal/privacy and payment gates remain incomplete.
- Applies to: roadmap, release readiness, product claims, docs.
- Boundary: Do not call the project public production-ready or paid-beta-ready without explicit owner approval and evidence.

### Current MVP scope is Telegram-first TXT/DOCX/EPUB

- Status: Active.
- Summary: The current closed-beta product scope is Telegram bot translation for authorized TXT/DOCX/EPUB documents.
- Rationale: This keeps quality, safety, operations and release gates tractable.
- Applies to: bot, adapters, QA, roadmap, future-format planning.
- Boundary: Future formats need separate approval, architecture review, fixtures and scoped issues.

### Future formats are committed direction, not current implementation approval

- Status: Active / Deferred.
- Summary: RTF, FB2, PDF/OCR, HTML/HTM, ODT, legacy DOC, MOBI, AZW3/KPF and CBZ/CBR/DJVU remain future scope.
- Rationale: Format support needs parser/resource safety, fixtures, dependency review and quality gates.
- Boundary: Do not implement a future format from roadmap mention alone.

### Payment path is blocked until Gate C

- Status: Active.
- Summary: Paid beta requires Telegram Stars/XTR flow, payment ledger, idempotency, refunds/support and reconciliation.
- Boundary: No paid jobs, payment UI, pricing/payment policy changes or paid-readiness claims without owner-approved Gate C work.

## Active Architecture Decisions

### Backend/persistent jobs are source of truth

- Status: Active.
- Summary: Translation work is modeled through persistent jobs/work units, scheduler/worker execution and object storage.
- Rationale: Long documents need durability, cancellation, partial output, retry and observability.
- Applies to: bot, worker, scheduler, storage, admin.

### Admin remains owner-only and SSH-tunneled

- Status: Active.
- Summary: Admin console is for owner/operator, not a public product surface.
- Boundary: Public admin exposure, auth/RBAC/security changes and deployment changes require explicit owner approval.

### External provider layer is internal

- Status: Active.
- Summary: DeepSeek-compatible provider routing/key/capacity behavior is internal. Users should not see a provider/model picker in current scope.
- Boundary: Provider config/key changes, meaningful live provider calls and user-facing provider behavior require approval.

### Bounded DeepSeek test-smoke standing approval

- Status: Active.
- Summary: Hermes/Codex agents may autonomously run local bounded DeepSeek smoke/probe tests inside the `AGENTS.md` standing approval envelope.
- Rationale: The owner wants routine local provider-backed checks to run without repeated micro-approvals while preserving cost, raw-data and release-claim boundaries.
- Applies to: local development tasks, Hermes/Kanban verification, provider smoke/probe commands, metadata-only reports.
- Boundary: The envelope allows at most 6 live provider calls and 60000 total reserved tokens per task, using existing repo scripts and current `DEEPSEEK_*` configuration. It does not approve provider configuration changes, new spend paths, Telegram/server/deploy operations, runtime/cache rollout, raw externalization, or release/quality/legal/public claims.

### Owner-only raw diagnostics are allowed locally

- Status: Active.
- Summary: Local owner-chat inspection of raw text, `.env*`, secrets, provider payloads and diagnostics is allowed when relevant.
- Rationale: The owner is using a local development workspace and wants less confirmation friction.
- Boundary: Do not commit, publish or externally share raw private material unless explicitly asked.

### Public/raw artifact boundary still matters

- Status: Active.
- Summary: Local raw discussion is allowed, but public/committed/support/release artifacts should not receive raw secrets/text/provider bodies by accident.
- Applies to: docs, GitHub, PRs, issues, release artifacts, support notes, public/customer surfaces.

## Active Glossary Decisions

### Glossary core remains language-neutral

- Status: Active.
- Summary: Target-language morphology/variant behavior belongs behind explicit terminology policy/adapter boundaries, not scattered RU/UK branches in glossary core.
- Rationale: Keeps future language support extensible and testable.

### First glossary-injected enabled/test-path units bypass cache

- Status: Active.
- Summary: Glossary-injected test/enabled paths should bypass existing translation cache unless a future approved cache-key issue changes this.
- Rationale: Avoid stale non-glossary reuse while output-affecting dimensions are incomplete.

### Prepared glossary package is a battle-test bridge

- Status: Active.
- Summary: Prepared packages can bridge owner/test Telegram jobs to runtime glossary context, but they are not the final durable glossary product model.
- Boundary: Do not infer durable registry, normal rollout, cache reuse, release/privacy policy or quality proof from prepared-package plumbing.

### Automatic glossary live evidence is currently no-go

- Status: Active.
- Summary: The latest bounded live automatic glossary smoke failed readiness.
- Rationale: RU prep did not produce READY package; UK runtime failed structural validation.
- Boundary: No runtime rollout, release readiness or quality claims without new evidence.

### Scanner v2 deferred after expanded audit evidence

- Status: Active.
- Summary: Keep deterministic scanner v1 plus candidate-quality gates and #690 quality-approved reducer diagnostic backfill for now; do not create a scanner-v2 shadow implementation issue from the #688-#692 evidence.
- Rationale: #690 attribution showed the #688 suspected missing target-backed durable candidates were present in scanner v1 output and lost at reducer/prep selection, then #690 backfill recorded 12 selected of 12 checked expected candidates with suspected missing count 0.
- Boundary: Future scanner-v2 work needs fresh metadata-only evidence of persistent scanner-level misses after #689/#690 gates. This does not approve scanner-v2 implementation, scanner v1 rewrite, runtime rollout, cache reuse, live provider work, provider config changes, durable state/storage/admin/retention changes or release/privacy/legal/support claims.
- Unknown: Real provider behavior, real-book translation quality and broader fixture coverage.

## Active Release / Safety Decisions

### Gate B before free closed beta

- Status: Active.
- Summary: Free closed beta requires Gate B evidence before go/no-go.
- Includes: real-file matrix, upload safety/TTL, DOCX/EPUB validation, restart/recovery, backup/restore, alerts/server smoke evidence.

### Beta safety accounting is not paid billing

- Status: Active.
- Summary: Cost/cap guard is operational beta safety, not a paid ledger.

### Release/legal/privacy/public claims need owner decision

- Status: Active.
- Summary: Public production, legal/privacy/AUP/support/refund text and readiness claims need explicit owner approval and evidence.

## Decisions Still Needed

- Free closed beta go/no-go after Gate B evidence.
- Final TTL/delete/retention policy for beta.
- Restore rehearsal cadence and backup visibility target.
- Alerts MVP definition.
- Paid beta timing and policy.
- Public admin hardening path, if ever exposed.
- Future format prioritization and fixture policy.

## Do Not Reinterpret

- Historical plans are not current roadmap unless the active roadmap says so.
- Local/fake/provider-boundary evidence is not release readiness.
- Passing structural validation is not semantic quality proof.
- Raw local owner-chat access is not permission to commit or publish raw material.
- Payment/pricing drafts are not paid beta approval.
- Deployment scripts/runbooks are not permission to deploy.
