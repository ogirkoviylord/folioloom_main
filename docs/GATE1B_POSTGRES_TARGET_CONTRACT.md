# Gate 1B PostgreSQL-target strict DOCX authorization contract

**Date:** 2026-07-24
**Source-pinned baseline:** `d9b55563f675e9da1393191daa2afe31a25d0c83` (`test(gate1b): verify durable binding boundaries (#837)`)
**Status:** Approved bounded target contract and delivery route. It is not PostgreSQL implementation, migration, runtime activation, Gate 1 closure, quality, beta, release, or deployment evidence.

## Purpose

Establish one backend-neutral strict-DOCX authorization contract. PostgreSQL is the intended durable/runtime backend; SQLite is its local/test/reference implementation. The contract governs only a new explicit strict DOCX admission route.

## Approved target decisions

| Decision | Target contract |
| --- | --- |
| Backend role | PostgreSQL is the durable/runtime target. SQLite is a conforming local/reference implementation. |
| Scope | New, explicit strict DOCX admission only. TXT, EPUB, ordinary DOCX, existing `with_glossary`, Telegram dispatch, cache policy, deployment and generic legacy-path migration remain out of scope. |
| Authorization objects | Immutable `DocumentCustody`, `GlossaryApproval`, and per-job `StrictJobGlossaryBinding` are the canonical semantics. |
| Approval reuse | One glossary approval may bind multiple strict jobs only when the approved custody and snapshot digest exactly match. Every job binding remains immutable. |
| Revocation | Revocation blocks new and retry claims. It does not promise cancellation of an already claimed or actively translating unit; cancellation policy is separate. |
| Unsupported backend | Missing strict capability returns a typed denial before writes and must not fall back to legacy `create_job()`. |
| Runtime glossary context | It may be called approved only after a strict-binding reader loads and revalidates it. No provider call is required unless an existing bounded script directly exercises that route. |

## Confirmed source-pinned baseline and M0 reconciliation

At source-pinned baseline `19dc045`, the #837 reconciliation documents a SQLite-only prototype: strict admission and claim guards exist in the SQLite store, while PostgreSQL lacks strict tables, APIs and claim predicates. `PersistentJobStore` remains the shared API; `StrictDocxJobStore` carries the four strict APIs (`src/translator_service/persistent_job_store.py:75-105`). These are historical baseline statements, not claims about current HEAD.

At that baseline, the SQLite implementation rejects reuse of an approval already bound to a strict job. That is a confirmed baseline behavior, not evidence that SQLite already conforms to the approved target's exact-match reuse rule. The baseline also does not demonstrate runtime consumption of `read_approved_glossary_snapshot()`.

The later dirty working-tree PostgreSQL strict-DOCX additions are not parity authority: Slice M0 quarantines their three strict table definitions for immutable migration v2 and supersedes their `SCHEMA_SQL` startup-DDL placement before merge. Migration v1 is the exact `19dc045` scheduler baseline, subject to a fail-closed legacy baseline validator. See `docs/GATE1B_POSTGRES_MIGRATION_RECONCILIATION.md`.

For source-pinned SQLite/legacy-path detail and evidence limits, read `docs/GATE1B_STRICT_DOCX_DURABLE_AUTHORIZATION_RECONCILIATION.md`.

## Bounded delivery route

1. Define and test the backend-neutral strict capability and typed unsupported-backend denial; SQLite passes selected contract cases and PostgreSQL gaps remain explicit.
2. Implement the repository-owned migration runner first: immutable v1 scheduler baseline, fail-closed legacy baseline stamp, then immutable strict-DOCX v2. The exact source ownership is recorded in `docs/GATE1B_POSTGRES_MIGRATION_RECONCILIATION.md`; no strict table may remain in evolving startup `SCHEMA_SQL`.
3. Add a strict binding snapshot reader that revalidates approval, custody, digest and schema before the selected strict runtime seam; preserve legacy behavior.
4. Add exactly one opt-in strict DOCX entrypoint accepting an approved `approval_id`; do not convert ordinary DOCX or `with_glossary` routes.
5. Collect focused metadata-only test evidence and independent reviews before one PR. PostgreSQL integration is `Unknown` unless the existing `TEST_POSTGRES_DSN` path runs.

## Explicit non-claims and stop conditions

This contract does not authorize or prove a production route, provider/cache change, Telegram change, public/admin exposure, deployment, data retention/delete policy, generic DOCX/`with_glossary` conversion, object-store versioning, PostgreSQL migration execution, runtime rollout, translation quality, Gate 1 closure, beta, or release readiness.

Stop for an owner decision rather than expanding scope if a follow-on requires any of those boundaries, cannot validate a complete legacy baseline for the explicit v1 stamp, or conflicts with the approved decisions above.
