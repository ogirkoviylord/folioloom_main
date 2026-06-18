# FolioLoom Current Project State

Date: 2026-06-18

## Summary

FolioLoom is a working closed-beta foundation for Telegram-first translation of authorized long documents. The product path is: trusted beta user uploads TXT/DOCX/EPUB in Telegram, confirms rights, selects translation mode and target language, receives preview/estimate, explicitly continues/confirms, then gets progress/cancel/status/history and a final or partial translated file.

The project is not paid beta and not public production.

## Stack

- Python 3.13.
- aiogram Telegram runtime.
- FastAPI API/admin app.
- Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- PostgreSQL scheduler storage for server runtime.
- SQLite fallback/runtime stores where explicitly configured.
- Local object storage under host `./var`.
- DeepSeek-compatible provider layer.
- TXT/DOCX/EPUB planners, adapters and assembly.

## Implemented Foundations

### Bot and User Flow

- `/start`, menu/help/language flows.
- TXT/DOCX/EPUB upload and validation path.
- Rights confirmation before translation work.
- Translation mode and target language selection.
- Preview/estimate before full translation.
- Continue/confirm before full processing.
- Progress/cancel/status/history-oriented flows.
- Partial/final output handling.
- My Books/history foundations.
- UI localization foundations across supported interface languages.

### Translation Core

- TXT, DOCX and EPUB extraction/planning/assembly.
- Persistent planners and persistent assembly for final and partial outputs.
- Format adapters with structure preservation foundations.
- Output contract checks and repair path for unsafe provider outputs.
- Russian and Ukrainian quality/profile foundations.
- Glossary/prepared-package foundations are in development; current live evidence does not prove rollout readiness.

### Backend, Persistence and Worker

- Local object storage for source, intermediate, partial and final files.
- SQLite local/fallback job/work-unit storage where configured.
- PostgreSQL scheduler store for server runtime.
- Scheduler runner and worker loop.
- Work-unit leases, retries, usage accounting, worker heartbeats and output keys.
- Beta-safe concurrency and provider-capacity foundations.
- Beta safety guard: kill switch, cost caps, reservation/accounting and admin visibility.

### Provider Layer

- DeepSeek-compatible chat completion client.
- Multiple internal API channel/key support.
- Key selection/failover/cooldown foundations.
- Adaptive throttling and provider circuit behavior.
- Admin-visible provider health/runtime/probe/balance surfaces.

### Admin / Operations

- Owner/admin login/session foundation.
- Settings, beta allowlist, provider keys/health, operations, live monitor, costs, security/audit surfaces.
- SSH-tunnel-only admin posture for closed beta.
- Docker Compose stack and deployment/restore scripts.
- Backup/restore tooling and runbooks.

## Main Gaps Before Free Closed Beta

- TTL cleanup/delete verification.
- Real-file TXT/DOCX/EPUB release matrix and report.
- EPUBCheck or equivalent release validation.
- DOCX openability/visual QA.
- Cancel/resume/restart validation.
- Backup visibility page and restore rehearsal evidence.
- Alerts MVP.
- Approved beta-server smoke evidence.
- Release-ready legal/privacy/AUP/support materials remain future/public-production work.

## Current Glossary Posture

Automatic/internal glossary work is active but not release-ready.

Confirmed:

- temporary user-facing glossary selector was superseded by internal automatic policy;
- local/fake prepared-glossary prep and package validation foundations exist;
- candidate-quality gates were added locally;
- scanner v2 was deferred for now;
- owner-only diagnostics boundaries exist for glossary runtime sidecars.

Blocking caveat:

- the bounded live automatic glossary smoke after the local/provider wiring was no-go: RU prep did not produce a READY package; UK rendered glossary context but runtime structural validation failed.

Do not claim live glossary quality, runtime rollout readiness, cache reuse readiness or release readiness without new reviewed evidence.

## Common Verification

- Full unit suite: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Targeted unit tests: `PYTHONPATH=src python3 -m unittest tests.test_<module>`
- Compile: `PYTHONPATH=src python3 -m compileall src`
- Local predeploy: `scripts/predeploy_check.sh`
- Server smoke: `scripts/server_smoke_check.sh` only with owner-approved environment access.

## Historical Detail

