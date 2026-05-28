# FolioLoom Release Gates

Canonical checklist for moving from restart to beta stages. A gate is complete
only when every blocker item is either checked or explicitly deferred in a
signed go/no-go note.

## Common Verification Commands

Run these for Gate A and again before every later promotion:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Global repo-wide ruff cleanup is not a gate. Targeted lint inside
`scripts/predeploy_check.sh` is the current lint gate.

## Gate A - Immediate Stabilization Complete

- [ ] `CURRENT_PROJECT_STATE.md`, `README.project.md`, `README.md`,
  `DOCUMENT_INDEX.md` and `docs/restart/` agree on project status.
- [ ] Old prototype-era specs/plans are marked or indexed as
  historical/superseded.
- [ ] `docker-compose.yml` service names are documented as `api`, `bot`,
  `worker`, `postgres`, `redis`.
- [ ] Runtime mount model is documented as `./var -> /app/var` and
  `./var -> /data`.
- [ ] Server env doc points to `.env.server.example`, not stale
  `.env.example`.
- [ ] Admin is documented as SSH-tunnel-only.
- [ ] Restore runbook uses current backup scripts and current compose model.
- [ ] Scheduler/runtime consistency smoke is documented.
- [ ] The common verification commands pass.
- [ ] `scripts/server_smoke_check.sh` passes on the target server or the missing
  server condition is recorded before go/no-go.

## Gate B - Free Closed Beta

- [x] Invite-only allowlist is editable from SSH-tunneled admin and can be
  enabled or disabled with an admin toggle.
- [x] Rights confirmation is shown before full processing.
- [x] Free preview exists before full translation. Evidence: PRs #57/#58/#59/#61
  and #67 are merged; issue #56 local verification passed focused
  preview/bot/service tests, full unittest suite, compileall and predeploy check
  on 2026-05-16. This checks only the preview item, not overall Gate B
  readiness.
- [x] Per-user cost caps/job limits are enforced by the Phase 4 operational
  beta safety guard.
- [x] Global cost caps are enforced by reservation-at-enqueue and scheduler
  claim guards.
- [x] Admin kill switch exists in Settings/Live visibility and stops new
  uploads/jobs and new scheduler claims without restart.
- [x] Upload hardening/quarantine baseline is active. Evidence: issue #73 local
  verification on 2026-05-28 added stdlib-only content/container validation
  before accepted source creation for TXT/DOCX/EPUB. Synthetic negative
  fixtures cover unsupported extensions, wrong extension/content mismatch,
  invalid/binary TXT, corrupt ZIP, traversal/absolute paths, oversized archive
  members and total uncompressed content, high compression ratio /
  zip-bomb-like archives and executable-looking embedded paths. Clean-scanned
  unsafe containers fail closed from quarantine without parser/sandbox calls,
  accepted original source objects, pending uploads or persistent jobs/work
  units, and upload-safety activity remains metadata-only. Local verification
  passed the focused upload/ledger/bot/worker/admin/adapter/order suite, full
  unittest, compileall, touched-file lint, diff hygiene and predeploy. This
  checks only the upload hardening/quarantine item; TTL/quarantine cleanup,
  real-file matrix, approved beta-server smoke and full Gate B readiness remain
  separate blockers.
- [x] Local malware/AV scanning gate is active before parsing, or explicitly
  deferred by owner in the Gate B evidence report. Public multi-engine services
  must not receive user documents by default. Evidence: issue #95 metadata-only
  local verification on 2026-05-27 passed focused scanner/upload/runtime/
  deployment tests, full unittest, compileall and predeploy; issue #109
  metadata-only local runtime smoke confirmed internal `clamd` was reachable and
  detected the safe EICAR test signature without real `.env*`, `var/`, live
  server or user data. This checks only the malware/AV scanning item, not issue
  #73 upload-hardening baseline evidence, TTL/quarantine cleanup, approved
  beta-server smoke or full Gate B readiness.
- [ ] TTL cleanup is active for sources, finals, partials and quarantine.
- [ ] Real TXT/DOCX/EPUB matrix is executed and stored as a release artifact.
- [ ] Cancel/resume/restart scenarios pass.
- [ ] Worker restart does not lose accepted jobs.
- [ ] Bot restart does not make existing jobs invisible.
- [ ] Scheduler worker capacity is consistent with provider channel capacity:
  one key at capacity 1 remains serial, and multiple free keys can progress
  multiple documents without duplicate work-unit claims.
- [ ] Provider failure creates diagnosable metadata and safe user messaging.
- [ ] EPUBCheck or equivalent release validation passes for EPUB fixtures.
- [ ] DOCX openability/visual QA passes for DOCX fixtures.
- [ ] Admin Alerts MVP is visible and tested.
- [ ] Backups visibility is visible in admin or a documented owner runbook
  report exists for the beta.
- [ ] Backup export passes `scripts/verify_backup_export.py`.
- [ ] Restore rehearsal passes from a backup artifact.
- [ ] Admin remains SSH-tunnel-only.
- [ ] No payment UI is exposed.
- [ ] No paid job can be started.
- [ ] Logs/admin do not expose raw document text.
- [x] Beta safety telemetry stores safe budget metadata only: job/user ids,
  reservations, usage counts, costs, statuses and reason codes. It does not
  store raw document text, prompts, translations or API keys.
- [x] The common verification commands pass. Evidence: issue #72 local
  verification on 2026-05-23 passed `PYTHONPATH=src python3 -m unittest
  discover -s tests` (`Ran 1046 tests`, `OK (skipped=13)`),
  `PYTHONPATH=src python3 -m compileall src`, and
  `scripts/predeploy_check.sh`. This is local evidence only; CI status remains
  Unknown unless visible PR/check evidence is inspected, and server smoke remains
  unchecked.
- [ ] `scripts/server_smoke_check.sh` passes on the beta server.

## Gate C - Paid Beta

- [ ] Telegram Stars/XTR invoice flow is implemented.
- [ ] `pre_checkout_query` is handled and tested.
- [ ] `successful_payment` is handled and tested.
- [ ] `telegram_payment_charge_id` is stored.
- [ ] Payment/order idempotency is tested.
- [ ] Persistent ledger exists for credits/payments.
- [ ] Reservation/capture/refund path exists.
- [ ] `/paysupport` exists.
- [ ] Reconciliation report exists.
- [ ] Support/refund policy is documented.
- [ ] Price snapshot is stored per order.
- [ ] Paid job starts only after payment/credit capture.
- [ ] Failed/cancelled paid job behavior is tested.
- [ ] Admin payment traceability exists without exposing secrets or raw text.
- [ ] Free preview still works before paid commitment.
- [ ] Gate B remains passing.
- [ ] The common verification commands pass.
- [ ] `scripts/server_smoke_check.sh` passes on the paid-beta server.

## Gate D - Public Production

- [ ] Public admin hardening is complete: HTTPS, stronger access layer,
  MFA/named admin accounts or equivalent, and an explicit access policy.
- [ ] Admin is no longer exposed only by accident or implicit network behavior.
- [ ] Public parser hardening is complete.
- [ ] Stronger public-production AV/quarantine flow is complete, including
  resource limits, scanner update visibility, quarantine retention evidence and
  an approved policy for any external scanning service.
- [ ] Offsite backups are configured.
- [ ] Scheduled restore rehearsals are documented and recent.
- [ ] Legal/privacy/AUP/refund docs are ready.
- [ ] Support workflow exists and is staffed.
- [ ] Incident runbooks exist.
- [ ] Larger eval corpus and release report exist.
- [ ] Monitoring/alerts cover provider, queue, worker, disk, backup and error
  conditions.
- [ ] Abuse/cost controls are tested under public-like load.
- [ ] Gate C remains passing.
- [ ] The common verification commands pass.
