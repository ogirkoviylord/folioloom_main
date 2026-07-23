# Glossary Engine → Workbench Architecture Synthesis

**Date:** 2026-07-24
**Status:** Active planning record; implementation requires the owner decision below
**Canonical strategy:** [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813) and `docs/CAT_WORKFLOW_GATES.md`

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

The local approval/rehearsal, bounded Workbench shell, pure DOCX preflight and truthful local-observation follow-up are already on `main` through PRs #819, #820, #824, #825, #833 and #834. Treat their merged code as current local-prototype evidence, not as durable document custody, runtime authority or a Gate 2 workflow claim.

## Owner decision required before the next coder card

Approve or reject this exact **local-only** contract:

1. A new in-memory `ManualGlossaryApproval` / local snapshot lock exists only for a prevalidated bounded DOCX fixture slice.
2. It binds an opaque fixture-local reference to the exact `GlossarySnapshot` signature.
3. A selected-content or signature change invalidates the lock.
4. A missing or mismatched lock fails closed before glossary selection, context rendering or runner preflight.

If approved, “local” means Python in-memory objects in a test process only. It excludes browser/admin persistence, file I/O, document upload/parser execution, provider/network calls, DB/storage, logs/telemetry/artifacts, resolver/job/worker/cache paths, Telegram and server operations. Process restart loses the local state.

## Approved planning sequence after that owner decision

1. **Engine contract discovery first:** source-pinned fields, validation, signature and invalidation invariants for the local lock; no runtime bridge.
2. **Shared vocabulary:** use `local snapshot lock` and `local structural preflight`; do not claim authorization, runtime readiness, glossary active in translation, job creation or export readiness.
3. **Local UX/prototype work second:** only after the contract and vocabulary are fixed.
4. **Representative quality evidence later:** before any automatic-runtime, beta or release claim.

## Explicit non-goals for the conditional first slice

No real document admission, parser/upload, TXT/EPUB expansion, actual translation, provider call, runtime/cache change, durable project/document state, storage/DB, scheduler/worker, Telegram, auth/RBAC, export, deployment, payment or release claim.

