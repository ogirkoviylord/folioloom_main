# Gate 1B PostgreSQL migration-first reconciliation (Slice M0)

**Date:** 2026-07-24
**Source-pinned baseline:** `075117788527526b355bbab27518a23473250613` (`test(gate1b): verify durable binding boundaries (#837)`)
**Task type:** docs-only / spike-discovery.
**Risk level:** high for follow-on schema/state work; this reconciliation itself is local metadata-only and makes no code, database, provider, deploy, PR, or merge change.
**Approval status:** approved only for this no-runtime M0 reconciliation. The existing owner-approved bounded implementation scope is the versioned migration route in the attached planning packet; migration implementation remains separately gated by the approved scope and its acceptance criteria.

## Goal

Quarantine the dirty unversioned strict-DOCX PostgreSQL work against `19dc045`, identify the exact v1 baseline and v2 strict-schema ownership, and prevent the current startup-DDL variant from becoming merge authority.

## Confirmed facts

- At `19dc045`, `src/translator_service/postgres_scheduler.py` has one unversioned `SCHEMA_SQL` bootstrap payload for the existing scheduler tables and two provider-lease partial unique indexes. It contains no strict-DOCX custody, approval, or binding DDL.
- The current working tree adds 30 strict-DOCX DDL lines at `src/translator_service/postgres_scheduler.py:210-239`: `glossary_snapshot_custody`, `glossary_approvals`, and `strict_job_glossary_bindings`. Those lines are inside the same evolving `SCHEMA_SQL` string.
- The current working tree also adds strict capability, admission/read/revocation, claim-guard, deletion-guard, and test hunks. They depend on the three tables but are not themselves migration SQL.
- The current bootstrap path remains `open_persistent_job_store()` → `initialize_postgres_scheduler_schema(store.connection)` (`src/translator_service/persistent_job_store.py:133-151` and `src/translator_service/postgres_scheduler.py:475-480`). It still splits and executes `SCHEMA_SQL`; it has no migration ledger, checksum validation, baseline stamp, or migration-specific advisory lock.
- `TEST_POSTGRES_DSN` integration tests are present but not evidence for this M0 task because no database was run.

## Exact ownership for the successor implementation

### Migration v1 — immutable scheduler baseline

**Owner:** new migration module only (expected `src/translator_service/postgres_migrations.py`).

**Payload:** the complete pre-existing scheduler bootstrap schema represented by `SCHEMA_SQL` at source pin `19dc045`, including the existing scheduler tables, provider-slot tables, and the two existing provider-slot partial unique indexes. Preserve the baseline SQL semantically as found; do not mix strict-DOCX objects into v1 and do not fold in a generic schema cleanup.

**Bootstrap transition:** v1 is the only version eligible for a legacy no-ledger baseline stamp after a complete structural validation. A partial/unknown pre-ledger state must fail closed and must not be stamped.

### Migration v2 — strict DOCX durable schema only

**Owner:** new migration module only, as an immutable numbered v2 SQL payload.

**Move exactly these current dirty DDL lines out of `SCHEMA_SQL`:**

1. `glossary_snapshot_custody` definition: current `postgres_scheduler.py:210-218`.
2. `glossary_approvals` definition: current `postgres_scheduler.py:220-230`.
3. `strict_job_glossary_bindings` definition: current `postgres_scheduler.py:232-239`.

This current diff contains no strict-DOCX `CREATE INDEX` statement. Do not invent one in v2 without a separately reviewed requirement.

**Must not remain:** the three table definitions must not be appended to or executed through the legacy evolving `SCHEMA_SQL` startup path once v2 owns them.

## Non-DDL strict hunks: later parity/review ownership

The following dirty hunks are **not** part of the v2 SQL payload. They require rebase onto the migration-backed capability and targeted review rather than blind copying:

| Current location | Successor slice | Reason |
| --- | --- | --- |
| `persistent_job_store.py:75-124` | M1/M3 | Backend-neutral strict capability and unsupported-backend helpers. M1 wires migration bootstrap; M3 owns the service/entrypoint use. |
| `postgres_scheduler.py:244-280`, `301-450` | M2 | Null-safe scheduled-claim predicate. The prior review finding remains: revoke and both direct/scheduled claim paths need one PostgreSQL-safe serialization protocol; current SQL-string checks do not prove the race invariant. |
| `postgres_scheduler.py:505-755` | M2 | PostgreSQL custody/approval/read/admission implementation. It may be retained only after v2 provides its tables and the new migration runner has completed. |
| `postgres_scheduler.py:757-769`, `1281-1323` | M2 | Strict table test cleanup and strict non-delete behavior. No retention/cleanup policy change is authorized. |
| `tests/test_postgres_scheduler.py:53-285`, `562-875` | M1/M2 | Contract checks that currently assert the unversioned `SCHEMA_SQL` shape must be rewritten to assert migration definitions/runner behavior; real race evidence needs the guarded two-connection `TEST_POSTGRES_DSN` test. |

## Required successor boundaries

- One repository-owned migration authority with immutable numbered payloads and checksums; no third-party migration dependency.
- Fresh PostgreSQL state applies v1 then v2. Legacy no-ledger state is stamped only after complete v1 structural validation.
- Unknown version, checksum mismatch, non-contiguous history, partial baseline, or failed migration must fail closed without a blind stamp.
- No database execution, data cleanup/backfill/delete, deployment/server operation, provider call, Telegram operation, public artifact, PR, merge, or production dependency is part of M0.

## Assumptions, Unknowns, and TBD

- **Assumption:** the `19dc045` `SCHEMA_SQL` payload is the only repository-visible legacy scheduler baseline. It is the source pin for the successor validator, not proof of any deployed database shape.
- **Unknown:** whether an existing real PostgreSQL database matches that baseline. Do not infer this from local code or run M0 against a database.
- **Unknown:** whether the current dirty strict PostgreSQL code has all required direct-claim/revoke serialization and DSN race evidence. Existing local tests do not establish that invariant.
- **TBD:** exact typed migration/bootstrap error names and the structural-check query set; define these in M1 tests before implementation.

## Acceptance criteria for M0

1. The source pin, v1 baseline, and exact v2 DDL ownership are recorded above.
2. Active strict-DOCX docs state that unversioned startup-DDL strict parity is superseded before merge.
3. No code/schema runtime action, database execution, PR, commit, or merge occurs.
4. The downstream design/implementation packet can distinguish migration DDL from later strict behavior hunks and carries the stated stop conditions.

## Verification

- `git diff --check 19dc045` verifies the inspected dirty diff has no whitespace errors.
- Source inspection of the cited current and pinned files verifies the stated ownership boundaries.
- No unit/integration test or PostgreSQL command is required for this docs-only M0 task; a database execution would exceed scope.

## Out of scope

Generic migration framework work, deployment, server migration execution, database repair/backfill/cleanup, legacy DOCX conversion, ordinary DOCX/`with_glossary` routing, runtime provider activation, cache policy, retention policy, payment/legal/public text, quality/release claims, PR, merge.
