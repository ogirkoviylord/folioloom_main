# Gate 1 Manual Glossary Source-Seam Audit

**Date:** 2026-07-21

**Status:** source-backed Council audit complete; implementation not yet approved

**Council records:** `t_951349c6` (Interface Contract), `t_dd2d0236` (source-seam audit)

## Purpose

Record what the repository currently proves about a future manual, author-approved glossary path, and define the narrowest safe next technical experiment.

This is not a release claim, a Gate 1 closure, or an approval to change runtime behavior.

## Owner decisions already made

- **Authority A:** reuse the current owner-local development boundary. No auth/RBAC redesign belongs in this slice.
- **Custody A:** use an ephemeral local rehearsal. No database, durable glossary/document state, retention design, or migration belongs in this slice.
- Development evidence may be rich and temporary: local Council/Kanban artifacts may retain useful source locations, structured payload shapes, diagnostics, traces, timing/cost/process observations and screenshots. Such evidence must be inventoried for later reduction or removal.
- Do not independently publish credentials, secrets, private manuscripts/translations, or provider payloads to public GitHub/PR/release/support surfaces.

## Confirmed repository seams

### Document boundary

- TXT/DOCX/EPUB validation is in `src/translator_service/documents.py` (`SUPPORTED_UPLOAD_FORMATS`, `validate_document_upload`, `validate_document_content`).
- `bot_translation_service.py:confirm_pending_upload_rights` is Telegram pending-upload state, not a general manual glossary-approval boundary.

### Glossary contract and prompt context

- `src/translator_service/glossary_contracts.py` contains `GlossarySnapshot`, `GlossaryEntry`, snapshot validation, layers (`hard`, `soft`, `diagnostic`) and existing statuses including `owner_pinned` / `locked`.
- `src/translator_service/glossary_selection.py` provides bounded glossary selection.
- `src/translator_service/glossary_prompt_context.py` renders bounded prompt context.

### Runner, preflight, status and cache

- `translation_runner.py` contains `GlossaryRuntimeAdapterHookConfig`, glossary policy/preflight, effective-decision and callback-metadata seams.
- Existing runner configuration consumes a plan/context mapping rather than a `GlossarySnapshot` directly. A future snapshot-to-plan/context conversion is a new, explicitly scoped helper boundary; it must not be presented as existing runner capability.
- Preflight has compact reason/status/count metadata. Existing reasons include `source_term_or_alias_absent` and `prompt_context_budget_exhausted`.
- A rendered, effective glossary context bypasses cache `get` and `put`; fallback returns to ordinary cache behavior. Any later test must spy actual cache calls, not infer cache behavior from flags.

## What the audit does *not* establish

The source audit does not prove:

- provider adherence to locked terms;
- translation quality or representative before/after improvement;
- Gate 1 completion, rollout readiness, beta readiness or production readiness;
- a reusable author-approval lifecycle or manual glossary entrypoint;
- durable storage, retention or a generic document/project model;
- deployed behavior.

Existing persistent EPUB/rehearsal/resolver/archive paths are useful regression evidence, but are not evidence for a no-DB, no-resolver ephemeral manual glossary path.

## Conditional next experiment

If separately approved, the next code slice must be named and limited as a:

> **DOCX-only pure in-process structural rehearsal test**

It may use only:

```text
prevalidated bounded DOCX fixture slice
+ preconstructed valid GlossarySnapshot
+ explicit in-memory owner approval
→ snapshot validation
→ selection
→ prompt-context rendering
→ existing runner preflight/effective-decision seam
→ structured local result
```

It must exclude provider calls, Telegram, resolver/job/store/logger/archive wiring, persistent storage, filesystem evidence roots, UI, document-import lifecycle, cache-key/reuse changes, and automatic/battle-test semantic changes.

## Required owner decision before code

Define the in-memory approval contract:

1. **Representation** — the explicit in-memory object/flag that signals owner approval.
2. **Binding** — whether approval is bound to snapshot identity, signature, or both, plus the opaque document context.
3. **Currentness** — when a changed snapshot invalidates the approval.
4. **Mismatch behavior** — whether missing or mismatched approval refuses before runner/selection/rendering, or permits an explicitly labelled fake-only no-glossary observation.

### Recommended decision

Use a `ManualGlossaryApproval` in-memory object bound to the opaque document reference and exact glossary snapshot signature. A selected-content change invalidates it. Missing or mismatched approval should **fail closed before runner invocation**; it should not silently use the existing fail-open runtime fallback.

## Temporary evidence policy for a later local run

For the pure in-process test, useful evidence should remain in test-process captures: structured result, callback metadata, request/context capture, cache counters and diagnostics.

If a later richer temporary run is desired, approve it separately with:

1. one declared untracked evidence root;
2. an inventory of every sink/artifact written there;
3. containment checks for sidecars and diagnostics;
4. an explicit owner-approved cleanup operation and post-cleanup verification.

## Verification evidence from the audit

The audit source-map worker ran:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_glossary_contracts \
  tests.test_glossary_selection \
  tests.test_translation_runner \
  tests.test_epub_glossary_rehearsal_archive
```

Result: **94 passed**. Provider calls: **0**. The result is regression/seam evidence for the current working tree only.
