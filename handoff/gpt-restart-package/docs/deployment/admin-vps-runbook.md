# Admin Console VPS Runbook

This runbook deploys the FolioLoom admin console on the same OVH Ubuntu 24.04
VPS that runs the bot. The first production-safe access mode is SSH tunnel only:
the admin HTTP port binds to `127.0.0.1` on the VPS and is not exposed to the
public internet.

## Network Model

```text
Laptop browser -> SSH tunnel -> VPS 127.0.0.1:62062 -> api container:8000
```

Postgres and Redis stay inside the Docker Compose network. They are not
published on the VPS public interface.

## One-Time Server Setup

Install Docker and the Compose plugin on Ubuntu 24.04, then clone or update the
repository on the VPS.

Create the server env file from the server example:

```bash
cp .env.server.example .env
```

Fill the required values in `.env`:

```env
ENVIRONMENT=production
SERVICE_NAME="FolioLoom"
DEEPSEEK_API_KEY=...
TELEGRAM_BOT_TOKEN=...
POSTGRES_PASSWORD=...
DATABASE_URL=postgresql://translator:<same-postgres-password>@postgres:5432/translator
REDIS_URL=redis://redis:6379/0
OBJECT_STORAGE_ROOT=/data/object-storage
PERSISTENT_JOBS_DB_PATH=/data/runtime/jobs.sqlite3
USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3
TRANSLATION_RUN_LOG_ROOT=/data/run-logs
ADMIN_DB_PATH=/data/runtime/admin.sqlite3
ADMIN_OWNER_PASSWORD=...
ADMIN_SESSION_SECRET=...
ADMIN_SECRET_MASTER_KEY=...
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
outside the backup bundle too, for example in a password manager. Without that
same key, restored encrypted admin secrets cannot be decrypted. Do not commit
`.env`.

## Start Or Update

```bash
docker compose up -d --build
docker compose ps
scripts/server_smoke_check.sh
```

The API container listens on the VPS loopback only:

```text
127.0.0.1:62062 -> api:8000
```

## Open Admin Console

From your laptop:

```bash
ssh -L 62062:127.0.0.1:62062 user@YOUR_VPS_IP
```

Then open:

```text
http://127.0.0.1:62062/admin/live
```

## Useful Checks

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f bot
docker compose logs -f worker
```

Health endpoint through the tunnel:

```bash
curl http://127.0.0.1:62062/health
```

Admin pages require login:

```bash
curl -I http://127.0.0.1:62062/admin/live
```

The server smoke check also verifies that the bot container can open
`ADMIN_DB_PATH`, validate `ADMIN_SECRET_MASTER_KEY`, and write a harmless admin
deployment probe row. That is the practical proof that the admin console and bot
share the same runtime SQLite database after deploy.

## Data Persistence

Compose persists runtime state in the host `./var` directory mounted into both
`/app/var` and `/data` for `api`, `bot`, and `worker`. Production env paths
should use `/data/...` so every container reads and writes the same files:

- `ADMIN_DB_PATH=/data/runtime/admin.sqlite3`: admin settings, encrypted
  secrets, audit, activity, runtime reload/status rows;
- `OBJECT_STORAGE_ROOT=/data/object-storage`: source and translated files;
- `TRANSLATION_RUN_LOG_ROOT=/data/run-logs`: translation logs;
- `PERSISTENT_JOBS_DB_PATH=/data/runtime/jobs.sqlite3` and
  `USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3`: local runtime
  state.

PostgreSQL data lives in the `postgres-data` Docker volume.

Back up both Postgres and the host `var` runtime directory before risky deploys
or migrations. The backup script includes `admin.sqlite3`; the master key is
still your responsibility.

## Security Notes

- Keep `/admin` behind SSH tunnel until there is a domain, HTTPS, and stronger
  access control.
- Do not publish Postgres or Redis ports on the VPS public interface.
- Do not paste real secrets into chat or tickets.
- Rotate `ADMIN_OWNER_PASSWORD`, `ADMIN_SESSION_SECRET`, and
  `ADMIN_SECRET_MASTER_KEY` if they are ever exposed.
- A future public admin setup should add HTTPS, IP allowlist, Cloudflare Access
  or VPN, MFA, and named admin accounts.
