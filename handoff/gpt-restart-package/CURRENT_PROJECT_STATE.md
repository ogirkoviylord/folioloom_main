# FolioLoom Current Project State

Generated for project restart handoff.

## Repository Snapshot

- Workspace audited: `/Users/yuriimedvediev/Documents/New project 2`
- Current branch: `main`
- Git state during audit: clean, tracking `origin/main`
- Python source files: 93
- Test files: 87
- Approximate source size: 35.8k Python LOC
- Approximate tests size: 24.8k LOC
- Approximate markdown docs size: 18.6k LOC

## Verification Results

Commands run during audit:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Result:

```text
Ran 811 tests in about 10 seconds
OK (skipped=10)
```

```bash
PYTHONPATH=src python3 -m compileall src
```

Result: passed.

```bash
scripts/predeploy_check.sh
```

Result: passed. This includes Docker Compose config, selected server hardening
tests, targeted lint, CLI smoke checks, shell syntax, documentation checks,
compile checks, and diff hygiene.

Important caveat:

```bash
python3 -m ruff check --no-cache src tests scripts
```

does not currently pass globally. It reports many historical style/import/line
length issues. The project uses a narrower targeted lint gate in
`scripts/predeploy_check.sh`.

## What The Project Is

FolioLoom is currently a closed-beta-ready foundation for a Telegram-first
document translation service. It supports TXT, DOCX, and EPUB translation flows
with DeepSeek-compatible providers, persistent job/work-unit storage, object
storage, partial/final result assembly, admin tooling, server deployment
scripts, backup/restore workflow, and extensive tests.

It is not yet a paid public production service.

## Implemented Capabilities

### Bot And User Flow

- aiogram Telegram runtime.
- Main menu, help, language selection, document upload, target-language choice,
  estimate, confirmation, progress, cancellation, status/history-oriented
  flows.
- Interface localization across Russian, Ukrainian, French, Spanish, English,
  and Dutch.
- TXT/DOCX/EPUB upload validation and translation path.
- Cooperative cancellation with partial output.
- My Books/history foundations with ownership checks, download, resume/cancel
  affordances, and delete confirmation.

### Translation Core

- TXT, DOCX, and EPUB extraction/planning/assembly.
- Format-adapter layer for TXT/DOCX/EPUB.
- Persistent planners for TXT/DOCX/EPUB.
- Persistent assembly for final and partial TXT/DOCX/EPUB output.
- DOCX handling includes headers, footers, footnotes, endnotes, comments,
  tables/pseudo-tables, basic run formatting, hyperlinks, hidden text
  preservation, subscript/superscript, structured/protected text.
- EPUB handling includes spine order, XHTML text blocks, inline formatting,
  notes/footnote anchors, OPF/NCX auxiliary text, repair helpers.
- Translation memory/context foundations.
- Output contract checks and repair path for unsafe provider outputs.

### Backend / Persistence / Worker

- Local object storage for originals, intermediate work-unit files, partials,
  and finals.
- SQLite persistent job/work-unit store.
- PostgreSQL scheduler store.
- Scheduler runner and worker loop.
- Work-unit leases, retries, attempts, usage accounting, worker heartbeats,
  partial/final output keys.
- Docker Compose services for `api`, `bot`, `worker`, `postgres`, and `redis`.
- Production env example uses `SCHEDULER_BACKEND=postgres`.
- Shared runtime volume model: host `./var` mounted to `/data` for api/bot/worker.

### Provider / DeepSeek

- DeepSeek-compatible chat completion client.
- Multiple internal API channel/key support.
- Key pool cooldown/failover behavior.
- Admin-visible provider runtime status and reload request flow.
- Provider validation/probe surfaces.

### Admin Console

Implemented admin areas include:

- owner login/session auth;
- RBAC model;
- settings;
- encrypted secret storage;
- integration registry and connection rows;
- AI provider keys;
- provider validation/probe/runtime status/reload;
- overview action center;
- live monitor;
- translation run logs and detail/download;
- user activity;
- user list/details;
- security events;
- operations/jobs;
- token/cost analytics;
- quality run trigger;
- audit logging;
- deployment smoke checks.

The admin console is intended to be accessed through an SSH tunnel for now, not
public internet exposure.

### Deployment / Operations

- `docker-compose.yml` for server stack.
- `scripts/deploy_server.sh`
- `scripts/predeploy_check.sh`
- `scripts/server_smoke_check.sh`
- `scripts/server_status.sh`
- `scripts/backup_server_data.py`
- `scripts/verify_backup_export.py`
- VPS runbook.
- Restore runbook.

### Quality / Safety

- Security telemetry and user cooldowns.
- Prompt-injection regression tests.
- Model output safety checks.
- Russian target-language profile and deterministic quality checks.
- Ukrainian target-language profile, source-pair guidance, anti-calque rules,
  and deterministic checks.
- Translation policy signatures include prompt/protection/adapter/profile
  versions.
- Document sandbox v1 for TXT/DOCX/EPUB extraction, planning, and assembly via
  constrained subprocess.

## Main Gaps Against The Roadmap

### Product / UX

- No polished Simple vs Advanced interface mode.
- No finalized Standard / High Precision or Draft / Balanced / Careful quality
  selection in user flow.
- No user-facing per-order controls for terminology, name handling, hidden text,
  link text, glossary, or quality route.
- No real support-ticket backend or support admin workflow.
- No formal rights/permission confirmation flow.
- No free preview flow.

### Payments / Commercial

- Pricing strategy exists in docs.
- Basic in-memory billing/order/refund domain exists.
- No real Telegram Stars integration.
- No Stripe or payment-provider integration.
- No persisted production payment ledger.
- No production credits/balance implementation.
- No paid-order refund operations in admin.

### Reliability / Beta Gate

- Unit tests are strong, but the project still needs a real-file closed-beta
  test matrix:
  - upload/estimate/translate for real TXT/DOCX/EPUB;
  - cancel and partial result;
  - resume after bot/worker restart;
  - worker crash/retry behavior;
  - backup and restore rehearsal;
  - admin status accuracy after deploy.
- Full end-to-end server run with real DeepSeek keys should be recorded as a
  release artifact.

### Evaluation / QA

- No complete golden eval corpus.
- No visual DOCX QA using LibreOffice previews.
- No EPUBCheck or equivalent release gate.
- No structured manual QA record format for real sample failures.
- Language quality beyond Russian/Ukrainian profile foundations is still thin.

### Production Safety

- No TTL cleanup for uploaded/generated files.
- No antivirus/quarantine flow.
- No public-production parser/container hardening gate completed.
- No public admin hardening: HTTPS, MFA, named admin accounts, IP allowlist or
  Cloudflare Access/VPN.
- Redis is present in compose but scheduler correctness is DB-scan based; queue
  policy/fair scheduling/backpressure/user limits still need product decisions.

### Admin Roadmap

The practical admin roadmap appears mostly implemented through:

- Environment safety banner
- Overview Action Center
- Jobs/queue screen
- Token/cost analytics
- Provider health

Missing or not visible as complete standalone modules:

- Alerts MVP
- Backups and recovery visibility page

Backup scripts and restore runbooks exist, but the admin page for backup
visibility is not yet implemented as a clear owner-facing surface.

## Recommended Restart Decision

The best next move is probably a free closed beta before paid beta.

Rationale:

- The engineering foundation is strong enough to test with real documents.
- Quality/reliability/user trust are still the biggest unknowns.
- Payment, legal rights flow, refunds, support, and public-production hardening
  would add complexity before the core user promise is fully proven.

Suggested near-term goal:

> Stabilize a closed-beta loop where a trusted user can upload TXT/DOCX/EPUB,
> receive a good final or partial result, resume after interruption, and where
> the owner can diagnose provider/runtime/jobs/logs/backups from admin.
