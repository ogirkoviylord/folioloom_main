# FolioLoom Release Gates

Canonical strategy issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813)
Canonical gate document: `docs/CAT_WORKFLOW_GATES.md`

A gate is complete only when every blocker item is either checked or explicitly deferred in a signed owner go/no-go note.

## Common Verification Commands

Run these for local verification when code changes:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Global repo-wide ruff cleanup is not a gate. Targeted lint inside `scripts/predeploy_check.sh` is the current lint gate.

## Current Gate Model

The old Telegram-first Gate B/C plan is superseded as the primary release compass.

Current release/product gates:

1. Gate 0 — Product reframe / scope lock.
2. Gate 1 — Glossary / terminology control prototype.
3. Gate 2 — CAT-like author workflow thin slice.
4. Gate 3 — Quality evidence gate.
5. Gate 4 — Design partner free alpha.
6. Gate 5 — Operational safety gate.
7. Gate 6 — Paid pilot.
8. Gate 7 — Self-serve paid beta.
9. Gate 8 — Public production.

## Gate 0 — Product Reframe / Scope Lock

- [x] Canonical strategy issue exists: #813.
- [x] Canonical gate document exists: `docs/CAT_WORKFLOW_GATES.md`.
- [x] Telegram is classified as harness / auxiliary channel, not the defining product surface.
- [ ] First ICP for design-partner alpha is explicitly selected.
- [ ] First representative evidence corpus is selected.
- [ ] First CAT workflow child issues are split from #813.

## Gate 1 — Glossary / Terminology Control Prototype

- [ ] Manual/author-approved glossary input path is defined.
- [ ] Manual/author-approved glossary edit/review path is defined.
- [ ] Locked/pinned terms override automatic suggestions.
- [ ] Automatic candidates are suggestions only unless separately approved.
- [ ] Preflight status shows glossary readiness and warnings.
- [ ] Post-run metadata-only compliance report exists.
- [ ] Before/after evidence shows controlled glossary improves critical terms on representative samples.
- [ ] No silent fallback from glossary-enabled to no-glossary behavior.
- [ ] Automatic glossary runtime remains experimental/shadow until representative live evidence passes.

## Gate 2 — CAT-like Author Workflow Thin Slice

- [ ] TXT/DOCX/EPUB import creates durable structure/segments.
- [ ] Glossary review/edit happens before translation.
- [ ] Translation draft/suggestions can be generated from approved glossary state.
- [ ] QA findings are visible and actionable.
- [ ] Export uses current approved/edit state.
- [ ] Telegram harness can exercise/deliver the workflow where useful.

## Gate 3 — Quality Evidence Gate

- [ ] Representative matrix covers at least 3-5 documents for first alpha evidence.
- [ ] Matrix includes fiction with recurring names and terminology-heavy material.
- [ ] Matrix includes DOCX/EPUB/TXT as applicable to current scope.
- [ ] Metadata-only before/after evidence is recorded.
- [ ] Structural validity is separated from semantic/terminology quality.
- [ ] Locked-term adherence is sampled and reported.
- [ ] Reviewer preference / usable-draft judgment is recorded.
- [ ] Raw source text, translations, prompts, provider bodies and secrets are not published in release artifacts.

## Gate 4 — Design Partner Free Alpha

- [ ] 3-5 trusted design partners or owner-equivalent test cases are selected.
- [ ] Users understand the AI-assisted draft / glossary-control framing.
- [ ] Outputs are rated usable / needs review / not usable with reason tags.
- [ ] Willingness-to-pay signal is collected.
- [ ] Support burden and failure reasons are recorded.
- [ ] No paid/public/production claim is made.

## Gate 5 — Operational Safety Gate

Old Gate B issues carry forward here. Completing these items does not, by itself, prove product value or paid readiness.

- [x] Invite-only/owner-gated access foundations exist.
- [x] Rights confirmation foundations exist.
- [x] Preview/estimate before full translation foundations exist.
- [x] Cost caps / job limits / kill switch foundations exist.
- [x] Upload hardening/quarantine baseline evidence exists from the old Gate B path.
- [x] Local malware/AV scanning evidence exists from the old Gate B path.
- [x] Provider failure safe diagnostics and user messaging evidence exists.
- [x] Logs/admin raw-text redaction synthetic evidence exists.
- [x] Common local verification baseline exists.
- [ ] CAT real-file import/segment/glossary/export matrix (#75).
- [ ] CAT DOCX export LibreOffice visual QA (#76).
- [ ] CAT workflow cancel/resume/restart recovery (#81).
- [ ] CAT project TTL cleanup and explicit delete behavior (#82).
- [ ] CAT Alerts owner report (#83).
- [ ] CAT Backups owner report (#84).
- [ ] Approved backup export manifest verification (#85).
- [ ] Restore rehearsal for CAT project state (#86).
- [ ] CAT app/server smoke evidence, bot harness optional (#87).
- [ ] CAT Beta Readiness Report replaces old final Gate B report (#88 superseded by #813).

## Gate 6 — Paid Pilot

Paid pilot is blocked until Gates 1-5 have enough positive evidence.

- [ ] Paid pilot scope and cohort are owner-approved.
- [ ] Support/refund expectations are written.
- [ ] Quality/workflow evidence supports asking for payment.
- [ ] Cost/runtime variance is bounded enough for pricing.
- [ ] Failure/partial behavior is clear to the user.
- [ ] No self-serve paid beta claim is made.

## Gate 7 — Self-Serve Paid Beta

- [ ] Payment ledger exists.
- [ ] Payment/order idempotency is tested.
- [ ] Price snapshot is stored.
- [ ] Capture/refund/cancel behavior is tested.
- [ ] `/paysupport` or equivalent support path exists.
- [ ] Reconciliation report exists.
- [ ] Admin payment traceability exists without exposing secrets or raw text.
- [ ] Gate 5 and Gate 6 remain passing.

## Gate 8 — Public Production

- [ ] Public admin hardening is complete.
- [ ] Public legal/privacy/AUP/support docs are ready.
- [ ] Offsite backups are configured.
- [ ] Restore rehearsals are scheduled and recent.
- [ ] Incident runbooks exist.
- [ ] Abuse/cost controls are tested under public-like load.
- [ ] Public marketing claims are evidence-bound and owner-approved.
- [ ] Gate 7 remains passing.

## Do Not Reinterpret

- Old Gate B/C passing would not prove CAT product value.
- Payment plumbing would not prove paid readiness.
- Local/fake/provider-boundary glossary evidence does not prove glossary runtime quality.
- Structural validation does not prove semantic/terminology quality.
- Telegram harness evidence does not replace CAT workflow evidence.
