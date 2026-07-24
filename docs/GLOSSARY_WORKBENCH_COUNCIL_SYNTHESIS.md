# Glossary Engine → Workbench Council Synthesis

**Date:** 2026-07-24
**Status:** Active planning record; the bounded local contract was owner-approved and its local sequence is merged through #836. It is not durable authorization or Gate 1 closure.
**Canonical strategy:** [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813) and `docs/CAT_WORKFLOW_GATES.md`
**Council graph:** proposal `t_63de6d11`; GPT-Critic `t_447a802f`; DeepSeek-Critic `t_326b3f83`; MiMo-Critic `t_db14176c`; required GLM-Council `t_c80d9020`; synthesis `t_bcd10381`.

## Decision in one sentence

Keep and adapt the existing glossary engine, but make manual author control the future authority: automatic candidates are suggestions, persistent/runtime plumbing is deferred infrastructure, and no further Workbench/runtime coding may infer a durable approval lifecycle from the current contracts.

## Confirmed reusable foundations

- `GlossarySnapshot`, `GlossaryEntry`, validation, evidence references, signatures and entry statuses (`owner_pinned`, `locked`) are real reusable contracts.
- Scanner, candidate-quality/reducer paths, bounded selection, prompt-context rendering, prepared packages and metadata-only compliance diagnostics are useful engine components.
- TXT/DOCX/EPUB adapter plans and structural block anchors are the reusable document-structure seam.
- Existing persistent resolver/runtime code is durable infrastructure and regression evidence; it is **not** Workbench authority or proof of terminology quality.

## Boundaries that must remain explicit

- Telegram upload/rights/job/delivery is an auxiliary harness, not the Workbench domain model.
- Automatic candidates and prepared-package readiness are recommendations/diagnostics, never silent terminology authority.
- Compliance metadata proves local configured-form/policy observations only; it does not prove literary or semantic translation quality.
- `glossary_editor_packets.py` is internal prompt-oriented packaging, not an author-editor API.
- Passing local/fake/provider-boundary checks does not prove runtime activation, Gate 1 closure, product readiness or release readiness.

## Current integrated baseline

The local approval/rehearsal, bounded Workbench shell, pure DOCX preflight, truthful local-observation follow-up and local snapshot-lock wiring are already on `main` through PRs #819, #820, #824, #825, #833, #834 and #836. Treat their merged code as current local-prototype evidence, not as durable document custody, runtime authority, a Gate 1 closure or a Gate 2 workflow claim.

## Completed owner decision and local sequence

The completed owner approval covered this exact **local-only** contract:

1. A new in-memory `ManualGlossaryApproval` / local snapshot lock exists only for a prevalidated bounded DOCX fixture slice.
2. It binds an opaque fixture-local reference to the exact `GlossarySnapshot` signature.
3. A selected-content or signature change invalidates the lock.
4. A missing or mismatched lock fails closed before glossary selection, context rendering or runner preflight.

The owner approved this local-only contract and the bounded sequence is merged through #836. “Local” means Python in-memory objects in a test process only. It excludes browser/admin persistence, file I/O, document upload/parser execution, provider/network calls, DB/storage, logs/telemetry/artifacts, resolver/job/worker/cache paths, Telegram and server operations. Process restart loses the local state.

## Completed local planning sequence and approved strict-DOCX route

1. **Engine contract discovery:** source-pinned fields, validation, signature and invalidation invariants for the local lock; no runtime bridge.
2. **Shared vocabulary:** use `local snapshot lock` and `local structural preflight`; do not claim authorization, runtime readiness, glossary active in translation, job creation or export readiness.
3. **Local UX/prototype:** completed within the bounded local contract through #836.
4. **Strict-DOCX route:** the source-pinned reconciliation is merged through #837. Follow the approved PostgreSQL-target contract in `docs/GATE1B_POSTGRES_TARGET_CONTRACT.md`; it is not PostgreSQL parity, migration, runtime activation or Gate 1 closure evidence.
5. **Representative quality evidence later:** before any automatic-runtime, beta or release claim.

## Explicit non-goals for the conditional first slice

No real document admission, parser/upload, TXT/EPUB expansion, actual translation, provider call, runtime/cache change, durable project/document state, storage/DB, scheduler/worker, Telegram, auth/RBAC, export, deployment, payment or release claim.

## Council participation and dissent

All four critical lanes completed. GLM-Council participated successfully as the owner-required independent critic; its role remained advisory and review-only. The synthesis accepted its correction that the persistent resolver is durable-but-deferred infrastructure, not an undurable legacy path.
