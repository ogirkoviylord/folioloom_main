# FolioLoom Restart Specification

Canonical restart-ТЗ для следующей фазы проекта. Этот документ заменяет старые
prototype-era roadmap формулировки. Для конкретных stage gates см.
`docs/restart/release-gates.md`.

## Product Definition

| FolioLoom is | FolioLoom is not yet |
| --- | --- |
| Telegram-first service for translating authorized long-form documents | Paid public SaaS |
| Tool for books, chapters, manuscripts, editorial materials, public-domain and rights-holder documents | "Translate any copyrighted book" service |
| TXT/DOCX/EPUB beta product | PDF/OCR/MOBI/FB2 converter |
| Backend-first service with persistent jobs/work units and object storage | Arbitrary file parser |
| DeepSeek-compatible APIs as internal provider layer | Provider marketplace or model playground |
| Admin-observable through SSH-tunneled admin console | Public admin product |

## Restart Decision

Decision: free closed beta first.

Paid beta is blocked because the repo does not yet have a production-ready
Telegram Stars/XTR flow, persistent payment ledger, refund/support path,
reconciliation, formal rights confirmation, free preview flow, full real-file
eval corpus, EPUBCheck/equivalent gate, DOCX visual QA, TTL cleanup,
quarantine/AV/public parser hardening, Alerts MVP or Backups visibility page.

Before paid beta, FolioLoom must have:

- Telegram Stars invoice flow.
- `pre_checkout_query` handling.
- `successful_payment` handling.
- Stored `telegram_payment_charge_id`.
- Idempotent order/payment handling.
- Persistent credits/payment ledger.
- Reservation/capture/refund path.
- `/paysupport`.
- Reconciliation report.
- Support/refund policy.
- Price snapshot per order.
- Admin traceability for paid orders without exposing secrets or raw text.

## Target Stage

Target stage: closed-beta stabilization.

Goal: a trusted allowlisted user can upload an authorized TXT/DOCX/EPUB file,
receive a good final or partial result, resume after interruption, delete data,
and the owner can diagnose runtime/provider/jobs/logs/backups from admin.

## Required Closed-Beta Flow

```text
allowlist check
-> upload TXT/DOCX/EPUB
-> validation/quarantine
-> rights confirmation
-> target language selection
-> estimate
-> free preview
-> user confirms full translation
-> persistent job/work units
-> worker processing
-> progress/cancel
-> partial/final result
-> My Books/history/resume/delete
-> TTL cleanup
```

## Backend Invariants

- Backend is the source of truth.
- Telegram bot state is an adapter, not durable state.
- Every accepted document has durable metadata, object, job and work-unit
  records.
- Progress derives from work units.
- Cancel, resume and restart are safe and idempotent enough for beta.
- Output assembly is deterministic and recoverable.
- Admin never exposes secrets or raw book text by default.
- DeepSeek/provider choice is internal, not user-facing.
- TXT, DOCX and EPUB adapters stay separate.
- Scheduler correctness must not depend on a single in-memory bot process.
- Provider failures must create diagnosable metadata without storing raw
  document text in logs.

## Technical Specification For Next Phase

### Format scope

| Format | Beta expectation | Release validation |
| --- | --- | --- |
| TXT | Preserve paragraphs, line breaks, poetry-like layout and Cyrillic text | Real small/long/poetry fixtures |
| DOCX | Preserve openability, common manuscript structure, tables, headers, footers, footnotes, comments, hyperlinks and basic formatting | LibreOffice/manual visual QA or equivalent |
| EPUB | Preserve spine order, nav/ToC, XHTML validity, anchors, notes and images where applicable | EPUBCheck or equivalent release validation |

No PDF, OCR, MOBI, FB2, batch ZIP or arbitrary containers in the next beta.

### Worker, scheduler and object storage rules

- Server runtime uses `SCHEDULER_BACKEND=postgres`.
- `api`, `bot` and `worker` must share the same `/data` runtime mount.
- Host `./var` is the current runtime root for object storage and SQLite
  runtime/admin files.
- Accepted source files, work-unit artifacts, partials and finals use generated
  storage object keys, not user filenames as paths.
- Work units own retry/attempt metadata.
- Worker restart must not lose accepted jobs.
- Bot restart must not make existing jobs invisible.
- Server smoke checks must fail loudly on scheduler/runtime mismatch.

### Admin rules

- Closed-beta admin remains SSH-tunnel-only.
- No public admin exposure before public-production hardening.
- Admin may show metadata, provider health, job status, costs and safe run
  diagnostics.
- Admin must not show raw document text by default.
- Admin must not show real secrets.
- Immediate admin gaps: Alerts MVP and Backups visibility.

### Upload safety

Closed beta accepts only `.txt`, `.docx` and `.epub`. The service must not trust
filename or `content-type` alone. DOCX/EPUB ZIP containers need inspection for
path traversal, entry count, uncompressed size, compression ratio and suspicious
paths. Rejected or suspicious files go through user-facing rejection/quarantine
behavior without leaking raw text into logs.

Detailed rules live in `docs/restart/upload-safety-and-retention.md`.

### TTL and retention

Closed-beta default retention:

| Data | Default |
| --- | --- |
| Source file | 7 days after final/cancel/delete, immediate on explicit delete where safe |
| Final result | 30 days or until delete |
| Partial result | 14 days |
| Quarantine | 7 days |
| Logs | Metadata only |
| Audit/security | Longer, redacted |

### QA and real-file validation

Closed beta needs a real-file corpus using public-domain, owned, synthetic or
otherwise authorized files only. Release reports must cover real TXT, DOCX and
EPUB fixtures plus negative and ops scenarios. See
`docs/restart/real-file-test-matrix.md`.

### Payment boundaries

- No payment UI exposed in free closed beta.
- No paid job starts before payment/credit capture in paid beta.
- No Stripe/YooKassa/card flow as the immediate Telegram path.
- Telegram Stars/XTR is the first paid-beta path.
- Pricing docs are draft only until Gate C.

## Roadmap By Stage

| Stage | Goal | Key work |
| --- | --- | --- |
| Immediate stabilization | Make beta foundation coherent and gated | Docs cleanup, deploy smoke, allowlist, quotas/caps, rights confirmation, preview, upload safety baseline |
| Free closed beta | Validate real authorized documents with trusted users | Real-file matrix, cancel/resume/restart, TTL, alerts, backup visibility, restore rehearsal, no payment UI |
| Paid beta | Charge safely inside Telegram | Stars/XTR flow, ledger, idempotency, refunds, `/paysupport`, reconciliation, payment admin traceability |
| Public production | Expose broader service responsibly | Public admin hardening, legal/privacy/AUP/refund docs, support workflow, stronger parser/AV, offsite backups, incident runbooks |

## Must-Fix Blockers

### Free closed beta blockers

- [ ] Rights confirmation.
- [ ] Beta allowlist.
- [ ] Per-user quotas.
- [ ] Global cost cap.
- [ ] Admin kill switch.
- [ ] Free preview.
- [ ] Upload hardening/quarantine.
- [ ] TTL cleanup.
- [ ] Real-file matrix.
- [ ] EPUBCheck or equivalent gate.
- [ ] DOCX openability/visual QA.
- [ ] Alerts MVP.
- [ ] Backups visibility.
- [ ] Docs cleanup.
- [ ] Scheduler/runtime consistency.

### Paid beta blockers

- [ ] Telegram Stars/XTR invoice flow.
- [ ] Persistent ledger.
- [ ] Idempotency.
- [ ] Stored `telegram_payment_charge_id`.
- [ ] Refund path.
- [ ] `/paysupport`.
- [ ] Reconciliation.
- [ ] Support/refund policy.
- [ ] Price snapshot per order.
- [ ] Payment admin traceability.

### Public production blockers

- [ ] HTTPS/public admin hardening.
- [ ] MFA/named admin accounts/access layer.
- [ ] Public parser hardening.
- [ ] Stronger AV/quarantine flow.
- [ ] Offsite backups.
- [ ] Scheduled restore rehearsals.
- [ ] Legal/privacy/AUP/refund docs.
- [ ] Support workflow.
- [ ] Incident runbooks.
- [ ] Larger eval corpus.

## Do Not Build Yet

- Paid beta first.
- Stripe/YooKassa/card flow as immediate path inside Telegram.
- Subscriptions.
- Coupons/referrals/team seats.
- PDF/OCR/MOBI/FB2/batch ZIP.
- Public website/customer portal.
- WhatsApp/Discord/API channels.
- Full glossary UI.
- Arbitrary custom prompts.
- User-facing provider/model selection.
- Advanced BI.
- Public admin.
- Global ruff cleanup as a release blocker.

## Release Gates

Use `docs/restart/release-gates.md` as the gate checklist.

Minimum technical commands for every serious release decision:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Gate summary:

| Gate | Meaning |
| --- | --- |
| Gate A | Immediate stabilization complete |
| Gate B | Free closed beta ready |
| Gate C | Paid beta ready |
| Gate D | Public production ready |

## Next 2-Week Engineering Plan

The detailed plan is in `docs/restart/two-week-engineering-plan.md`.

Summary:

| Week | Focus | Exit signal |
| --- | --- | --- |
| Week 1 | Source-of-truth docs, deployment consistency smoke, beta mode, allowlist, quotas/cap/kill switch, rights confirmation, free preview, upload hardening baseline | Gate A candidate |
| Week 2 | TTL/delete verification, Alerts MVP, Backups visibility, real-file corpus/report, closed-beta go/no-go | Gate B candidate |
