# Two-Week Engineering Plan

Goal: reach a credible free closed-beta go/no-go without adding new product
scope. Do not build payment, new formats, subscriptions, public admin, public
website or user-facing provider selection in this window.

## Week 1

| Slice | Goal | Deliverables | Acceptance criteria |
| --- | --- | --- | --- |
| Source-of-truth docs cleanup | Make the repo understandable in 5 minutes | Updated `README.project.md`, `README.md`, `DOCUMENT_INDEX.md`, `CURRENT_PROJECT_STATE.md`, restart docs and status banners | New reader can identify current stage, blockers, gates and historical docs |
| Deployment consistency smoke | Prove docs match compose/runtime reality | Updated deployment runbooks and `server-beta.md` superseded note | Docs name `api/bot/worker/postgres/redis`, `.env.server.example`, `./var -> /data`, SSH tunnel and current scripts |
| Beta mode / allowlist | Restrict closed beta to trusted users | Implemented: Telegram ID allowlist with user-facing rejection copy, admin add/remove UI and enforcement toggle | Non-allowlisted user cannot start upload/translation flow when enforcement is on |
| Quotas / cost cap / kill switch | Bound provider cost during free beta | Per-user quota, global cap, admin kill switch behavior | Quota/cap/kill switch stop new full translations safely |
| Rights confirmation | Make authorization explicit | Rights confirmation screen/copy before full processing | User must confirm they own rights, have permission, or use public-domain/authorized text |
| Free preview | Let users see quality before full job | Preview work-unit route and UX copy | Full translation cannot start before preview and explicit confirmation |
| Upload hardening baseline | Prevent unsafe containers from reaching workers | TXT/DOCX/EPUB validation, ZIP inspection, quarantine/rejection metadata, local malware/AV scanner design | Negative fixtures reject/quarantine safely, scanner behavior is designed or explicitly deferred, and no raw text leaks |

Week 1 exit: Gate A candidate plus implemented or explicitly scoped Gate B
foundation items.

## Week 2

| Slice | Goal | Deliverables | Acceptance criteria |
| --- | --- | --- | --- |
| TTL cleanup / delete verification | Bound retained source/result data | TTL cleanup job/process, delete verification, admin metadata | Source/final/partial/quarantine retention follows restart policy |
| Local malware/AV scanning implementation | Scan uploads before parsing without sending user files to public scanners by default | Scanner contract, safe verdict metadata, local scanner adapter after approval, EICAR/equivalent test fixture | Clean files may proceed; infected/unscanned/error files do not reach parser or workers; scanner errors fail closed for beta unless owner-approved otherwise |
| Alerts MVP | Surface owner-actionable operational failures | Minimal alert rules for provider, queue/worker, disk, backup, failed jobs | Admin owner can see current alerts without reading logs manually |
| Backups visibility | Make backup health visible | Admin page/card or explicit owner report showing latest backup/verify status | Owner can answer when last backup was created and verified |
| Real-file corpus / release report | Validate real TXT/DOCX/EPUB behavior | `real_corpus_manifest.yml` or equivalent, fixture run report | Real-file matrix covers happy path, negative fixtures and ops scenarios |
| Closed-beta go/no-go | Decide whether to invite users | Gate B checklist, known risks, rollback plan | Gate B is checked or blockers are listed with owner decision |

Week 2 exit: free closed-beta go/no-go note with release artifacts.

## Non-Goals For This Plan

- Paid beta.
- Telegram Stars/XTR implementation.
- Stripe/YooKassa/card flow.
- Subscriptions/referrals/coupons/team seats.
- PDF/OCR/MOBI/FB2/batch ZIP.
- Committed future formats beyond TXT/DOCX/EPUB, including FB2 from GitHub issue
  [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23), until issue
  #208 prioritizes them and separate format-specific implementation issues have
  Architect review and approval.
- Public admin.
- Public website/customer portal.
- WhatsApp/Discord/API channels.
- Full glossary UI or arbitrary custom prompts.
- Global ruff cleanup as a release blocker.
