# Admin Console VPS Runbook

Актуальный runbook для closed-beta deployment FolioLoom на VPS. Admin console
работает через FastAPI service `api`, но в closed beta остается доступным
только через SSH tunnel. Не публикуй `/admin` в интернет до public-production
hardening.

## Network Model

```text
Laptop browser -> SSH tunnel -> VPS 127.0.0.1:62062 -> api container:8000
```

Postgres and Redis stay inside the Docker Compose network. They are not
published on the VPS public interface.

## Compose Services

Current `docker-compose.yml` services:

- `api` - FastAPI health/admin app, published as `127.0.0.1:62062:8000`;
- `bot` - aiogram Telegram runtime;
- `worker` - background translation worker;
- `postgres` - PostgreSQL scheduler/job/work-unit state;
- `redis` - internal service, not the source of scheduler correctness.

The app containers share runtime state through:

```text
./var -> /app/var
./var -> /data
```

Production paths in `.env` should use `/data/...`.

## One-Time Server Setup

Install Docker and the Compose plugin on Ubuntu 24.04, then clone/update the
repo on the VPS.

Create server env from the current example:

```bash
cp .env.server.example .env
nano .env
```

Required values:

```env
ENVIRONMENT=production
SERVICE_NAME="FolioLoom"
TELEGRAM_BOT_TOKEN=
ADMIN_TELEGRAM_IDS=
BETA_ALLOWLIST_ENABLED=false
BETA_ALLOWLIST_TELEGRAM_IDS=
DEEPSEEK_API_KEY=
DEEPSEEK_API_KEYS=
DEEPSEEK_MAX_PARALLEL_PER_KEY=1
TRANSLATION_MAX_PARALLEL_UNITS=2
SCHEDULER_BACKEND=postgres
POSTGRES_DB=translator
POSTGRES_USER=translator
POSTGRES_PASSWORD=change-this
POSTGRES_DSN=postgresql://translator:change-this@postgres:5432/translator
DATABASE_URL=postgresql://translator:change-this@postgres:5432/translator
REDIS_URL=redis://redis:6379/0
OBJECT_STORAGE_ROOT=/data/object-storage
PERSISTENT_JOBS_DB_PATH=/data/runtime/jobs.sqlite3
USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3
TRANSLATION_RUN_LOG_ROOT=/data/run-logs
ADMIN_DB_PATH=/data/runtime/admin.sqlite3
ADMIN_OWNER_PASSWORD=
ADMIN_SESSION_SECRET=
ADMIN_SECRET_MASTER_KEY=
ADMIN_COOKIE_SECURE=false
ADMIN_PROVIDER_RUNTIME_RELOAD_SECONDS=30
```

Generate admin secrets on the VPS:

```bash
python3 - <<'PY'
import base64
import os
print("ADMIN_SESSION_SECRET=" + base64.urlsafe_b64encode(os.urandom(32)).decode())
print("ADMIN_SECRET_MASTER_KEY=" + base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
```

Use a long unique `ADMIN_OWNER_PASSWORD`. Keep `ADMIN_SECRET_MASTER_KEY`
outside the backup bundle, for example in a password manager. Without the same
key, restored encrypted admin secrets cannot be decrypted. Do not commit `.env`.
The same master key is required for encrypted admin-managed integration and
provider keys. If it is missing, the admin UI cannot store new keys.

For a small closed beta, start with conservative operational safety caps and
adjust the live values later from Admin -> Settings:

- `BETA_GLOBAL_DAILY_COST_CAP_USD=5.00`
- `BETA_GLOBAL_MONTHLY_COST_CAP_USD=50.00`
- `BETA_USER_DAILY_COST_CAP_USD=1.00`
- `BETA_USER_DAILY_JOB_LIMIT=3`

Phase 4 beta safety is an operational guard, not billing. New persistent jobs
reserve estimated budget before queue execution, global/user caps are checked
before enqueue, completed work units record prompt/completion token usage
idempotently, and the scheduler stops claiming new work when the live kill
switch or global caps are active. Telegram Stars/XTR and a paid ledger remain a
separate release gate.

`DEEPSEEK_API_KEY` and `DEEPSEEK_API_KEYS` remain valid runtime sources even
after additional DeepSeek keys are added from the admin UI. Admin-added keys and
env keys are additive: the balance view and runtime provider layer can use both
sets, and adding one admin key does not disable existing env keys.

`TRANSLATION_MAX_PARALLEL_UNITS` controls worker-side scheduled work-unit
capacity. Effective provider calls are also capped by DeepSeek channel capacity:
env/admin key count times each key's `DEEPSEEK_MAX_PARALLEL_PER_KEY` or
admin-configured max parallel value. Scheduler fairness caps are the final
layer, keeping one job/user from monopolizing available worker/provider slots.
For beta, keep `DEEPSEEK_MAX_PARALLEL_PER_KEY=1`; adding multiple healthy keys
then lets separate documents progress concurrently without sending two active
calls to the same key.

The AI Providers admin page reports DeepSeek runtime channel health without
secrets or document text: active requests, per-key capacity, cooldown,
429/503/timeout/auth/billing counters, latency and a redacted last error. A
degraded channel does not disable the key automatically in Phase 2; it lowers
selection priority and remains visible for operator action.
`Test all active keys` is paused while admin metadata reports active
translations or active provider requests. Wait until active translations and
provider requests return to 0 before running bulk key probes during an incident;
this avoids adding probe traffic while translations are using or about to use
provider capacity.

Adaptive provider throttling starts each worker runtime conservatively and
ramps DeepSeek concurrency after clean successes. 429/503/timeouts decrease the
local adaptive limit and cool down affected channels; auth/billing failures open
a provider circuit for the configured reset window. This is local per worker,
not a distributed global quota system.

If `/admin/ai-providers` shows an open provider circuit, do not raise
`TRANSLATION_MAX_PARALLEL_UNITS` as a first response. Check the redacted reason,
DeepSeek balance/auth state, per-channel 429/503/timeout counters and cooldowns.
The circuit should half-open after `DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS`.
Use runtime reload after fixing keys or balance.

## Start Or Update

Preferred deploy command:

```bash
scripts/deploy_server.sh
```

Manual equivalent for diagnostics:

```bash
docker compose up -d --build
docker compose ps
```

Run smoke checks after every deploy:

```bash
scripts/server_smoke_check.sh
scripts/server_status.sh
```

`scripts/server_smoke_check.sh` verifies:

- `.env` exists;
- `SCHEDULER_BACKEND=postgres`;
- Postgres credentials are not left at example defaults;
- compose config is valid;
- Postgres is reachable;
- bot source compiles inside container;
- admin deployment smoke passes from `api`, `bot` and `worker`;
- backup CLI is available.

## Open Admin Console

From your laptop:

```bash
ssh -L 62062:127.0.0.1:62062 user@YOUR_VPS_IP
```

Then open:

```text
http://127.0.0.1:62062/admin/live
```

Useful checks:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f bot
docker compose logs -f worker
curl http://127.0.0.1:62062/health
curl -I http://127.0.0.1:62062/admin/live
```

Admin pages require login. The tunnel URL should be reachable only from the
machine that opened the SSH tunnel.

## Closed-Beta Allowlist

The Telegram ID allowlist is managed from:

```text
http://127.0.0.1:62062/admin/settings
```

`BETA_ALLOWLIST_ENABLED=false` keeps the bot open while you collect candidate
Telegram IDs. You can add/remove IDs in admin settings at any time. Press
`Enable allowlist` only when the cohort is ready; after that, users outside the
list receive an invite-only message and new upload files are not downloaded.

`BETA_ALLOWLIST_TELEGRAM_IDS` is only a bootstrap/default list for fresh admin
state. Once admin settings are saved, the live SQLite setting is the source of
truth.

## Beta Safety / Cost Guard

Use the SSH-tunneled admin console for live beta safety operations:

- Admin -> Settings edits `BETA_TRANSLATIONS_PAUSED`, global/user cost caps and
  per-user job limits without restart.
- Admin -> Costs shows consumed, reserved and remaining beta budget, plus users
  near cap.
- Admin -> Live shows active kill switch/cap warnings for operator awareness.

To pause all beta translations without restart, enable
`BETA_TRANSLATIONS_PAUSED` in Admin -> Settings. New uploads/jobs are rejected
safely and the scheduler stops claiming new work. Existing idempotent
work-unit usage records remain counted once by work-unit id.

## Cost Or Provider Incident Response

If provider cost or error rate spikes:

1. Enable `BETA_TRANSLATIONS_PAUSED=true` in Admin -> Settings.
2. Check Admin -> Costs for consumed vs reserved budget.
3. Check Admin -> AI Providers for cooldown/circuit state.
4. Check Admin -> Live for active budget warnings and kill switch state.
5. Resume only after budget and provider health are understood.

## DeepSeek Balance

The DeepSeek balance snapshot is available in the SSH-tunneled admin console:

```text
http://127.0.0.1:62062/admin/ai-providers
```

Use `Refresh balance` after changing keys or topping up the DeepSeek account.
The UI shows a safe account-level balance snapshot and never displays real API
keys. If the page reports that secret storage is unavailable, set
`ADMIN_SECRET_MASTER_KEY`, restart the stack and try again.

### DeepSeek Key Operations

Use Admin -> AI Providers -> DeepSeek Keys to manage admin-stored provider keys.

Recommended operator flow:

1. Add or rotate the key.
2. Test the changed key.
3. Check Admin -> AI Providers for balance and provider health.
4. Click Reload DeepSeek runtime.
5. Watch Admin -> Live for channel cooldowns, circuit state and available slots.

Never paste raw keys into issue trackers, logs or chat. The admin UI stores
admin-managed keys encrypted and renders only masked values. Env keys remain
read-only and must be changed on the server.

## Data Persistence

Runtime files are persisted in the host `./var` directory mounted into `api`,
`bot` and `worker`.

- `ADMIN_DB_PATH=/data/runtime/admin.sqlite3` - admin settings, encrypted
  secrets, audit, activity and runtime reload/status rows.
- `OBJECT_STORAGE_ROOT=/data/object-storage` - source, intermediate, partial
  and final files.
- `TRANSLATION_RUN_LOG_ROOT=/data/run-logs` - safe translation run metadata.
- `PERSISTENT_JOBS_DB_PATH=/data/runtime/jobs.sqlite3` and
  `USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3` - local runtime
  stores where configured.

PostgreSQL data lives in Docker volume `postgres-data`.

Back up both Postgres and the host `var` runtime directory before risky deploys
or migrations. The backup script includes `admin.sqlite3`; the master key is
still your responsibility.

## Backup Commands

Create backup:

```bash
python3 scripts/backup_server_data.py --output-dir ~/folioloom_exports
```

Verify backup:

```bash
python3 scripts/verify_backup_export.py ~/folioloom_exports/folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

Restore rehearsal is documented in `docs/deployment/restore-runbook.md`.

## Security Notes

- Keep `/admin` behind SSH tunnel until there is a public-production hardening
  decision.
- Do not publish Postgres or Redis ports on the VPS public interface.
- Do not paste real secrets into chat, docs or tickets.
- Do not log raw document text in admin/run logs.
- Rotate `ADMIN_OWNER_PASSWORD`, `ADMIN_SESSION_SECRET` and
  `ADMIN_SECRET_MASTER_KEY` if they are ever exposed.
- Future public admin setup must add HTTPS, stronger access layer, MFA/named
  admin accounts or equivalent, and explicit incident/runbook coverage.
