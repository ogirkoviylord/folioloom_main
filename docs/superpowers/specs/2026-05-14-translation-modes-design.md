# Explicit Translation Modes Design

## Context

GitHub issue [#43](https://github.com/ogirkoviylord/folioloom_main/issues/43)
records an owner-reported quality problem: a structured Ukrainian
application/statement translated to Russian can be routed through behavior that
is too close to long-document/book translation. File extension alone is not a
reliable signal because the same DOCX format can represent an official
statement, a form, a table-heavy document, a chapter, or a manuscript.

This design stays inside the current free closed-beta scope: Telegram-first,
TXT/DOCX/EPUB only, invite-only beta, rights confirmation, cost caps, kill
switch, safe messaging, SSH-tunneled admin, and no payment/public-production
claims.

## Current Implementation Status

Restored to `origin/main` on 2026-05-16 after the original design document was
found only on local branch `codex/issue-52`.

Confirmed current status:

- Issues #44, #45, #46 and #47 are merged into current `origin/main`.
- Explicit mode selection, safe mode metadata, DOCX mode-specific routing and
  user-facing copy are implemented.
- Issue #55 is still open; preview generation must still be wired to the
  selected mode before translation modes are treated as fully consistent across
  preview and full translation.
- Issue #48 remains a spike for optional non-authoritative auto-suggestion.

This document remains the architecture/design reference for issue #43. For
current implementation status, use `docs/HANDOFF.md`, `docs/ROADMAP.md` and the
linked GitHub issues as the source of truth.

## Architect Verdict

Verdict: SAFE TO SPLIT, NOT SAFE AS ONE CODE CHANGE.

Issue #43 is feasible and useful, but implementation must be split because it
touches user-visible Telegram flow and adapter/profile routing. The design does
not require database migrations, deployment changes, payment changes, new
formats, public admin exposure, or new production dependencies.

Implementation requires human approval for the user-visible flow and final copy.
This document records the architecture decision and follow-up scope; it does not
claim the modes are implemented.

## Supported Modes

Initial supported modes:

- Document/form mode: for statements, applications, forms, official documents
  and structured documentation where layout, labels, tables, addresses,
  signatures, dates, numbers and non-translatable fields matter.
- Book/manuscript mode: for books, chapters, long manuscripts and editorial
  long-form text where continuity, paragraph flow, headings and prose style
  matter.

Mode selection must be explicit. Automatic detection may suggest a mode, but it
must not silently override the user's choice.

Working internal identifiers:

- `document_form`
- `book_manuscript`

Final localized Telegram labels remain an implementation-copy decision, but
they must preserve the distinction above.

## Telegram Flow Placement

The mode choice should appear after rights confirmation and before target
language/estimate.

Recommended flow:

1. User uploads TXT/DOCX/EPUB.
2. Upload validation runs.
3. User confirms rights.
4. Bot asks for translation mode.
5. User chooses document/form or book/manuscript.
6. Bot asks for target language.
7. Estimate is calculated using the selected mode.
8. User explicitly confirms before the full translation job starts.

Reasoning:

- Rights confirmation remains the legal/product boundary before processing.
- Mode affects estimate and routing, so it must be known before estimate.
- The full translation confirmation should summarize the selected mode.
- Free preview, when implemented, should use the selected mode and remain before
  full translation.

## Adapter Routing Contract

The first implementation should route the selected mode as metadata through the
existing bot/backend/adapter path instead of rewriting adapters.

Recommended contract:

- Store selected mode on the pending upload or translation request before job
  creation.
- Persist mode on created jobs/work units or equivalent safe metadata that is
  already appropriate for adapter/profile versions.
- Include mode in estimate inputs when estimate behavior differs.
- Include mode in prompt/profile selection and adapter planning where needed.
- Include mode in safe run metadata/admin details, but never include raw
  document text.

DOCX should be the first high-value routing target:

- Document/form mode should prefer strict structure preservation, table/field
  safety, conservative paraphrase, protected labels and non-translatable values.
- Book/manuscript mode should preserve document structure while allowing prose
  continuity and paragraph-level literary/editorial style behavior where current
  adapters already support it.

TXT/EPUB can initially accept and persist the same mode even if the first
behavioral difference is DOCX-only. That keeps the user contract stable while
implementation grows in small slices.

## Out Of Scope

- PDF, OCR, FB2, MOBI, batch ZIP or arbitrary parser support.
- User-facing provider/model picker.
- Payment, pricing, billing, refunds, paid jobs or payment UI.
- Deployment, bind addresses, public admin or production-readiness changes.
- Auth/security/RBAC/session changes.
- Retention, TTL, backup/restore, destructive operations or runtime `var/`
  changes.
- New production dependencies.

## Risks

- Wrong default or hidden auto-detection can keep routing structured documents
  through unsuitable behavior.
- Adding mode too late in the flow can make estimate/preview inconsistent with
  the final job.
- Persisting mode only in Telegram memory can break restart/resume behavior.
- Mode-specific prompts or metadata can leak unsafe raw text if logging/admin
  paths are expanded casually.
- Scope creep into PDF/FB2 would expand parser, fixture and release-gate scope.

## Required Tests

Focused tests for implementation follow-ups:

- Bot flow: rights confirmation happens before mode selection; mode selection
  happens before target language/estimate; translation cannot be confirmed
  without a mode.
- Estimate/confirmation: selected mode is included in pending upload/job inputs
  before full translation starts.
- Persistence/restart: selected mode survives the same persistence path used by
  jobs or pending uploads in the chosen implementation slice.
- Adapter routing: DOCX document/form mode reaches the DOCX planning/profile
  path separately from book/manuscript mode.
- Safety: no raw document text, prompts, translations, provider internals or
  secrets are added to logs/admin/telemetry by mode handling.
- Fixtures: use an authorized Ukrainian application/statement fixture or a
  synthetic fixture that demonstrates structure-sensitive routing without
  leaking real user text.

## Required Docs Updates

When implementation lands, update only the docs that correspond to confirmed
behavior:

- `README.md` and `CURRENT_PROJECT_STATE.md` if mode selection is implemented.
- `docs/HANDOFF.md` and `docs/ROADMAP.md` when issue follow-ups are completed
  or deferred.
- `docs/QUALITY_GATES.md` only if a new required gate is added.
- `docs/RISK_REGISTER.md` if risk status changes after tests/evidence.
- `docs/restart/release-gates.md` only if mode selection becomes a Gate B
  blocker or release evidence item by owner decision.

## Implementation Split

1. GitHub issue
   [#44](https://github.com/ogirkoviylord/folioloom_main/issues/44):
   Bot UX and pending state.
   Add explicit mode selection after rights confirmation and before target
   language. Acceptance: bot-flow tests prove ordering and no job starts without
   mode.

2. GitHub issue
   [#45](https://github.com/ogirkoviylord/folioloom_main/issues/45):
   Backend/job metadata.
   Carry selected mode through pending upload, estimate, job creation and safe
   metadata. Acceptance: focused service tests prove mode survives the chosen
   persistence boundary.

3. GitHub issue
   [#46](https://github.com/ogirkoviylord/folioloom_main/issues/46):
   DOCX routing/profile slice.
   Use `document_form` vs `book_manuscript` to choose DOCX-specific planning or
   prompt/profile behavior. Acceptance: adapter-routing tests and authorized or
   synthetic Ukrainian application/statement fixture.

4. GitHub issue
   [#47](https://github.com/ogirkoviylord/folioloom_main/issues/47):
   UX copy/localization.
   Add final labels and confirmation summary text in supported interface
   languages. Acceptance: message tests cover labels and safe wording.

5. GitHub issue
   [#48](https://github.com/ogirkoviylord/folioloom_main/issues/48):
   Optional auto-suggestion spike.
   Add non-authoritative suggestion only after explicit selection works.
   Acceptance: tests prove the user can override suggestion and suggestion does
   not start work automatically.

## Suggested Implementer Prompt

Implement the first small slice of GitHub issue #43: explicit translation mode
selection in the Telegram flow. Read `AGENTS.md`,
`docs/superpowers/specs/2026-05-14-translation-modes-design.md`,
`docs/CONTEXT_MAP.md` and `docs/QUALITY_GATES.md`. Keep scope to bot UX and
pending state only: after upload validation and rights confirmation, require the
user to choose `document_form` or `book_manuscript` before target language and
estimate. Do not change adapters, providers, payment, deployment, auth,
retention, database schema or supported formats. Add focused bot/runtime tests
that prove rights confirmation remains first, mode selection is required before
estimate/confirmation, and no translation job starts without a selected mode.
