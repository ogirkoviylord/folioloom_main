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
- [ ] Rights confirmation is shown before full processing.
- [ ] Free preview exists before full translation.
- [ ] Per-user quotas are enforced.
- [ ] Global cost cap is enforced.
- [ ] Admin kill switch exists and is tested.
- [ ] Upload hardening/quarantine baseline is active.
- [ ] TTL cleanup is active for sources, finals, partials and quarantine.
- [ ] Real TXT/DOCX/EPUB matrix is executed and stored as a release artifact.
- [ ] Cancel/resume/restart scenarios pass.
- [ ] Worker restart does not lose accepted jobs.
- [ ] Bot restart does not make existing jobs invisible.
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
- [ ] The common verification commands pass.
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
- [ ] Stronger AV/quarantine flow is complete.
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
