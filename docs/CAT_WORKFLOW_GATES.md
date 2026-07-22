# FolioLoom CAT-like Workflow Gates

Date: 2026-06-29
Canonical GitHub issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813)

## Status

This document is the active product/release strategy after the owner-approved reframe from the old Telegram-first Gate B/C plan.

The old Gate B/C documents are not deleted, but they must not be used as the primary release compass. Old Gate B items are now operational-safety carry-forward work under the CAT-like author workflow strategy.

## Product thesis

FolioLoom is an author/rightsholder translation workbench for authorized long documents.

The intended workflow is:

1. import TXT/DOCX/EPUB;
2. preserve document structure and stable segments;
3. review/edit glossary and terminology;
4. generate translation draft/suggestions;
5. surface QA/glossary/structure findings;
6. export a usable translated document;
7. use Telegram as a convenient upload/test/delivery harness, not as the defining product surface.

## Why the old plan changed

The old free closed beta plan focused on the Telegram bot pipeline and operational safety. That work is still valuable, but it does not prove translation quality or author value.

Recent glossary work showed that terminology control is a core quality prerequisite. Without author-controlled glossary/terminology, book and manuscript translations can be unacceptable even when the bot, storage, diagnostics, backup and payment plumbing work.

Paid beta is therefore blocked until glossary-controlled quality and author workflow value are evidenced.

## Gate 0 — Product reframe / scope lock

Goal: define FolioLoom as a CAT-like author/rightsholder workbench.

Exit criteria:

- ICP for the next cycle is explicit: author, editor, rightsholder or small publisher.
- Primary workflow is import -> glossary review -> translation draft -> QA -> export.
- Telegram is documented as harness / auxiliary channel.
- Paid beta/payment work is deferred until quality/workflow evidence exists.
- Old Gate B/C is treated as operational/payment infrastructure only.

## Gate 1 — Glossary / terminology control prototype

Goal: prove that controlled terminology materially improves real book/manuscript translation.

MVP path:

- manual/author-approved glossary first;
- automatic candidates as suggestions only;
- locked/pinned terms override automatic candidates;
- preflight status makes glossary readiness visible;
- post-run metadata report checks locked-term adherence and misses.

Exit criteria:

- Manual terms can be supplied or approved before translation.
- Runtime status shows whether glossary is actually active.
- There is no silent fallback from glossary-enabled to no-glossary behavior.
- Before/after evidence shows better critical-term consistency on representative samples.
- No claim is made that automatic glossary runtime is production-ready.

## Gate 2 — CAT-like author workflow thin slice

Goal: complete a minimal author workbench loop.

Required vertical slice:

1. import TXT/DOCX/EPUB;
2. expose durable document/chapter/segment structure;
3. review/edit glossary candidates;
4. translate a slice/document with approved glossary;
5. view QA findings;
6. export DOCX/EPUB/TXT;
7. optionally use Telegram for upload/delivery/test harness.

Exit criteria:

- End-to-end workflow passes on representative documents.
- Author/operator can correct terminology before full-document translation damage.
- Export uses current approved/edit state.
- QA findings are visible and actionable.

## Gate 3 — Quality evidence gate

Goal: replace optimism and local/fake tests with representative before/after evidence.

Evidence dimensions:

- structural validity;
- DOCX openability / EPUBCheck where applicable;
- glossary status and selected terms;
- locked-term adherence sample;
- untranslated/source residue;
- reviewer before/after preference;
- cost/runtime bounds;
- no raw/secret leak in normal artifacts.

Suggested matrix sizes:

- free alpha: 3-5 documents;
- private beta: 6-10 documents;
- paid beta: 12+ documents.

## Gate 4 — Design partner free alpha

Goal: learn whether authors/rightsholders value the workflow.

Scope:

- small high-touch cohort;
- free or discounted;
- explicit research/design-partner framing;
- authorized content only;
- no paid/public/production claims.

Exit criteria:

- users understand and use glossary controls;
- at least some outputs are rated usable draft / valuable with review;
- willingness-to-pay signal exists;
- failure reasons are categorized and actionable.

## Gate 5 — Operational safety gate

Goal: safely operate the proven CAT workflow on real files.

Carry forward old Gate B work here:

- real-file CAT import/segment/glossary/editor/export matrix (#75);
- DOCX export visual QA (#76);
- cancel/resume/restart recovery for CAT project state (#81);
- TTL/delete for project/source/segments/glossary/exports/diagnostics (#82);
- Alerts owner report (#83);
- Backups owner report (#84);
- backup manifest verification (#85);
- restore rehearsal for CAT project state (#86);
- CAT app/server smoke plus optional bot harness smoke (#87);
- CAT Beta Readiness Report, replacing old final Gate B report (#88 superseded by #813).

## Gate 6 — Paid pilot

Goal: charge only after value, quality and safety are credible.

Scope:

- limited high-touch paid jobs;
- clear support/refund expectations;
- conservative promise: AI-assisted draft translation with glossary controls;
- no publisher-ready or human-quality claim.

Exit criteria:

- users pay or commit to pay for the workflow;
- support/refund burden is known;
- glossary quality evidence is positive;
- critical failures are not known or have support policy coverage.

## Gate 7 — Self-serve paid beta

Goal: activate broader payment/self-serve mechanics only after paid-pilot evidence.

Required:

- payment ledger;
- idempotency;
- price snapshot;
- capture/refund/cancel behavior;
- support path;
- reconciliation;
- admin payment traceability without raw text/secrets;
- Gate 5/6 still passing.

## Gate 8 — Public production

Future only:

- public legal/privacy/AUP/support;
- public admin hardening;
- offsite backups;
- incident response;
- abuse controls;
- public marketing claims.

## Glossary stop rules

- Do not chase perfect automatic glossary as the blocker.
- Keep current deterministic scanner/candidate-quality gates unless fresh evidence proves scanner-level misses.
- Treat automatic runtime glossary as experimental/shadow/owner-only until representative live evidence passes.
- Manual author glossary controls are the MVP quality path.
- Every glossary improvement needs measurable acceptance: locked-term adherence, low-value candidate rate, structural validation, reviewer preference and no raw leak.

## Non-claims

This document does not approve code implementation, provider spend, deployment, server operations, runtime data mutation, destructive cleanup, backup/restore execution, DB migration, payment launch or raw-publication.

This document does not claim free beta, paid beta, public production, glossary runtime quality, cache reuse readiness or translation-quality readiness.
