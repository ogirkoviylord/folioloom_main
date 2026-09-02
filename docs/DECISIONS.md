# Decisions


## Status Labels

- Superseded: kept for history only; do not follow by default.
- Deferred: accepted direction, not approved for implementation now.
- Proposed: not approved yet.
- TBD: owner/human decision needed.
- Unknown: repository evidence missing.

## Active Product Decisions

### Workbench visual direction: Premium Author Studio baseline

- Status: Active / Deferred implementation.
- Summary: Future FolioLoom Workbench concepts should start from the **Premium Author Studio** direction selected by the owner after local Figma comparison. Treat it as a visual/product reference, not as an approved implementation packet or a pixel-for-pixel template.
- Current palette: Retain the selected Premium Author Studio warm-neutral palette as the single default for now. It is a design baseline, not a runtime theme/settings feature.
- Intent: The Workbench should feel like a calm, author-centred product room for working with a book and its terminology, rather than a Telegram harness, generic AI SaaS, CAT/TMS cockpit, spreadsheet, text-editor shell, or the current Admin surface.
- Rejected as primary directions: the table/card/dashboard-like Editorial, Precision and Guided Workflow explorations; Reader-First as the default Workbench surface. Do not revive their permanent queues, dense multi-column layouts, spreadsheet-like term tables, or document-reader shell as the default solely because they already exist in Figma.
- Deferred future ideas: (1) a distraction-free editor/focus mode that can hide surrounding chrome while retaining editor capability; (2) a warm, low-strain comfort-reading mode for an author rereading work; (3) selectable curated visual skins and later, potentially constrained palette choice. These belong in later UI/settings exploration, not the current primary screens. The comfort-reading control should not be placed on the main Workbench surface by default; palette customization must preserve readable contrast and semantic status colors rather than become arbitrary per-element color editing.
- Boundary: This does not approve code, a production UI, role/auth changes, reader/editor implementation, settings implementation, release claims, or a decision to expose raw manuscript text outside the authorized project context.

### Document Setup prototype boundary and contract

- Status: Active / owner-approved implementation boundary.
- Summary: Retain and amend the existing **OWNER-only** `Project Library → Document Setup → Glossary` flow as a narrow, author-centred orientation-and-handoff surface. Document Setup itself displays the selected DOCX context, has one primary continuation to the same existing Glossary destination, and does not save setup choices or start translation.
- Durable boundary: The existing Glossary destination remains owner-gated and durable; this decision neither makes it local/non-durable nor changes its authority, revision, save or lock behavior. Document Setup must not describe the whole chained flow as local/non-authoritative.
- Immediate state model: selected DOCX plus one generic fail-closed unresolved-context recovery. Empty/no-selection, unsupported, stale/changed and temporarily-unavailable states remain deferred until a controller-owned typed trigger and safe action semantics are separately approved.
- UX/copy boundary: Show selected filename and `Source format: DOCX`, a single primary `Continue to Glossary`, subordinate `Back to Project Library`, and a short Setup-only limitation. A compact disclosure may say that source language, target language and AI-assisted glossary terms are not part of Document Setup yet; it must be non-interactive and must not become a roadmap, capability promise or lifecycle claim.
- Deferred: source-language detection/correction, target-language catalog, AI glossary generation/candidates, broader format support, role/auth expansion, URL/context propagation changes, typed recovery states, and persistence/runtime binding of Setup choices.
- Boundary: This decision approves no provider/runtime/translation execution, schema/migration/cache/retention work, strict-DOCX change, route/URL change, raw-text exposure, Telegram/server/deploy action, payment, quality or release claim. A future implementation card must stay within this contract and receive independent review.

### Contextual terminology review and revision flow

- Status: Deferred / accepted product direction.
- Summary: Future source-target review should make glossary knowledge available in context wherever authorized document text is reviewed, rather than confining it to a standalone glossary page. A reader may softly mark glossary terms and open a compact term card with the approved source/target form, relevant grammatical data, literal/base meaning and a short description when present.
- Review interaction: The future reader may support bidirectional source-target alignment: selecting a word or phrase on either side can highlight the related **target/source span**. Alignment is probabilistic and may be many-to-one, one-to-many or ambiguous; the UI must not present an uncertain mapping as a certain one-word equivalence.
- Inline change path: From a term card, the author may propose a terminology change without leaving review. The flow must create a new glossary snapshot, show scope and impact, selectively regenerate affected fragment(s) with sufficient context when required, and present a reviewable diff for explicit approval.
- Integrity rule: An approved translation and its bound glossary snapshot remain immutable. A terminology change never silently edits the approved result; it produces a separately approved, snapshot-bound revision that preserves the prior revision and its evidence.
- Boundary: This is not approval to implement reader UI, automatic alignment, runtime glossary behavior, persistent revision storage, cache reuse, provider calls or global search-and-replace. Exact confidence policy, scope semantics, regeneration context and revision/custody implementation need a separately scoped design and evidence.

### CAT-like author workflow before paid/public launch

- Status: Active.
- Summary: The next meaningful milestone is a CAT-like author/rightsholder workflow with glossary-controlled quality evidence, not paid beta or public production.
- Rationale: The technical foundation is strong enough for owner/trusted design-partner learning, but controlled terminology quality, review workflow, real-file quality, TTL/delete, restore, server smoke, alerts, support/legal/privacy and payment gates remain incomplete.
- Applies to: roadmap, release readiness, product claims, docs.
- Boundary: Do not call the project free-beta-ready, paid-beta-ready, public-production-ready, glossary-runtime-ready or quality-ready without explicit owner approval and evidence.

### Current scope is CAT-like TXT/DOCX/EPUB with Telegram harness

- Status: Active.
- Summary: The current product direction is an author/rightsholder workbench for authorized TXT/DOCX/EPUB documents: import, structure/segments, glossary review/edit, translation draft, QA findings and export. Telegram is a harness, not the defining product surface.
- Rationale: This keeps quality, safety, operations and release gates tractable while focusing on the quality problem that blocks real user value.
- Applies to: CAT workflow, bot harness, adapters, QA, roadmap, future-format planning.
- Boundary: Future formats, public channels, paid flows and public surfaces need separate approval, architecture review, fixtures and scoped issues.

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

### Secret-store master key remains deployment-held for closed beta

- Status: Active.
- Issue: #723; owner decision: https://github.com/ogirkoviylord/folioloom_main/issues/723#issuecomment-4755337967.
- Summary: For the current owner-only / SSH-tunneled closed-beta posture, `ADMIN_SECRET_MASTER_KEY` remains a deployment-held master key outside the repository and outside the admin database. SQLite encrypted admin secret storage is acceptable only inside that boundary.
- Recovery rule: If the master key is lost or rotated without an owner-approved re-encryption plan, existing admin-managed encrypted secrets are unrecoverable; provider keys/secrets must be re-entered or rotated by the owner.
- Evidence: architecture review cited repository evidence that `Settings.admin_secret_master_key` is sourced from `ADMIN_SECRET_MASTER_KEY`, `SQLiteEncryptedSecretStore` uses AES-GCM and fails closed on a missing/invalid key, no repository evidence shows a re-encryption/recovery path, and runtime provider configuration can fall back to environment-held provider keys when admin-store channels are absent.
- Deferred/TBD: Managed secret stores, master-key rotation/re-encryption, multi-admin recovery, public-production hardening, and backup/restore runbook changes require separate owner-approved work.
- Boundary: Do not treat this as public-production hardening. This decision does not approve reading, printing, editing, rotating or migrating real secrets; `.env*` changes; server/deploy operations; DB/state/backup/restore operations; managed secret-store integration; or master-key rotation/re-encryption implementation.
- Unknown: The future managed secret-store provider, rotation/re-encryption workflow, multi-admin recovery design, and backup/restore runbook updates remain Unknown/TBD until separately scoped.

### External provider layer is internal

- Status: Active.
- Summary: DeepSeek-compatible provider routing/key/capacity behavior is internal. Users should not see a provider/model picker in current scope.
- Boundary: Provider config/key changes, meaningful live provider calls and user-facing provider behavior require approval.

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

### Glossary engine → Workbench authority boundary

- Status: Active planning decision; implementation contract TBD by owner.
- Summary: Retain the existing glossary contracts, scanner/candidate-quality paths, selection, context rendering and diagnostics as reusable engine foundations. Automatic candidates are suggestions; a prepared package or runtime observation is not author authority or quality proof.
- Authority: A future author-approved glossary must use an explicit approval/lock lifecycle bound to a precise snapshot and document context. Existing entry statuses (`owner_pinned` / `locked`) and signatures do not by themselves establish that lifecycle.
- Runtime: Persistent resolver/runtime code is durable but deferred infrastructure, not the Workbench product authority. Telegram remains a harness, not the authority model.
- Next decision: implementation and independent review of the approved durable DOCX authoring envelope below.
- Boundary: This does not approve durable custody, upload/parser work, provider calls, real translation/runtime integration, cache changes, DB/storage, Telegram/server operations, export, release or quality claims.

### Durable DOCX Glossary authoring envelope

- Status: Active / owner-approved implementation boundary (Council #2144; owner approval #2145, 2026-08-31).
- Summary: For an already registered owner DOCX, the Studio holds only a browser-local whole-snapshot working copy. `Approve and create revision` atomically creates an immediately-approved immutable exact-parent revision; it is an editable authoring record only and is not used by translation in this slice.
- Lock: `Make this revision read-only` is separately confirmed, document-level and irreversible in this slice. It preserves history and prevents successor authoring; recovery is re-import as a new document/custody. Durable drafts, per-term mutations/locks, unlock/revoke, runtime binding and Gate 1/quality claims remain out of scope.

## Active Release / Safety Decisions

### CAT-like author workflow reframe

- Status: Active.
- Canonical issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813).
- Canonical doc: `docs/CAT_WORKFLOW_GATES.md`.
- Summary: FolioLoom is now evaluated as an author/rightsholder translation workbench: import authorized TXT/DOCX/EPUB, preserve structure/segments, review/edit glossary, generate translation draft/suggestions, surface QA findings and export a usable document.
- Boundary: Telegram remains a harness / auxiliary channel, not the defining product surface.
- Boundary: Old Gate B/C is operational/payment infrastructure, not product readiness proof.

### Glossary / terminology control is a core quality prerequisite

- Status: Active.
- Summary: Paid beta and broader beta claims require evidence that glossary/terminology controls improve representative book/manuscript translation quality.
- Boundary: Manual/author-approved glossary controls are the MVP path; automatic glossary runtime remains experimental/shadow until representative live evidence passes.

### Operational safety carry-forward

- Status: Active.
- Summary: Old Gate B safety items remain useful under Gate 5 of `docs/CAT_WORKFLOW_GATES.md`: real-file matrix, upload safety/TTL, DOCX/EPUB validation, restart/recovery, backup/restore, alerts/server smoke evidence.
- Boundary: Completing operational safety items alone does not prove CAT workflow value, glossary quality, free beta readiness or paid beta readiness.

### Beta safety accounting is not paid billing

- Status: Active.
- Summary: Cost/cap guard is operational beta safety, not a paid ledger.

### Release/legal/privacy/public claims need owner decision

- Status: Active.
- Summary: Public production, legal/privacy/AUP/support/refund text and readiness claims need explicit owner approval and evidence.

## Decisions Still Needed

- Gate 0 ICP and first representative evidence corpus for CAT-like workflow.
- Minimum manual glossary control surface for Gate 1.
- Whether to approve the local-only DOCX snapshot-lock contract in `docs/GLOSSARY_WORKBENCH_COUNCIL_SYNTHESIS.md`.
- CAT workflow thin-slice scope and acceptance criteria.
- Design-partner free alpha timing and cohort.
- Final TTL/delete/retention policy for CAT project data.
- Restore rehearsal cadence and backup visibility target.
- Alerts MVP definition for CAT workflow health.
- Paid pilot timing and policy after quality/workflow evidence.
- Public admin hardening path, if ever exposed.
- Future format prioritization and fixture policy.

## Do Not Reinterpret

- Historical plans are not current roadmap unless the active roadmap says so.
- Local/fake/provider-boundary evidence is not release readiness.
- Passing structural validation is not semantic quality proof.
- Raw local owner-chat access is not permission to commit or publish raw material.
- Payment/pricing drafts are not paid beta approval.
- Deployment scripts/runbooks are not permission to deploy.
