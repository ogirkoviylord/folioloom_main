# FolioLoom Restore Runbook

Run this rehearsal before free closed beta and after any storage, scheduler or
admin DB change. The current server model is Docker Compose with services
`api`, `bot`, `worker`, `postgres`, `redis`, host runtime `./var`, and
PostgreSQL volume `postgres-data`.

## Inputs

You need three files from one backup timestamp:

```text
folioloom-db-YYYYMMDD-HHMMSS.sql
folioloom-files-YYYYMMDD-HHMMSS.tgz
folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

You also need the same `ADMIN_SECRET_MASTER_KEY` that encrypted the backed-up
`admin.sqlite3`. Store that key separately from the backup archive.

Verify the backup manifest before restore:

```bash
python3 scripts/verify_backup_export.py ~/folioloom_exports/folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

## Restore Rehearsal On A Fresh Server Copy

Use a test server or disposable copy first. Do not rehearse destructive restore
on the only live beta host.

For Gate B evidence, approved rehearsal environments are an owner-approved
disposable local Compose environment, disposable VPS/test server, disposable
copy of beta runtime data, or an explicitly approved beta environment. Running
backup/restore checks on live beta/server data requires explicit owner approval
for that exact run.

Release evidence must be metadata-only: manifest path/name or redacted manifest
summary, command output summary, pass/fail table, restore environment
description and known failures. Do not commit backup archives, restored files,
real `.env*` files, secrets, raw document text, prompts, translations or API
keys.

1. Stop FolioLoom:

```bash
docker compose down
```

2. Keep a local copy of current runtime files if they exist:

```bash
mv var "var.before-restore-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
mkdir -p var
```

3. Restore runtime files:

```bash
tar xzf ~/folioloom_exports/folioloom-files-YYYYMMDD-HHMMSS.tgz
```

The archive should recreate the host `var/` runtime tree. With production
`/data/...` container paths, this usually means `var/object-storage`,
`var/runtime/admin.sqlite3` and related runtime files on the VPS host.

4. Start only Postgres:

```bash
docker compose up -d postgres
```

5. Recreate database contents:

```bash
docker compose exec -T postgres psql -U translator -d translator -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T postgres psql -U translator -d translator < ~/folioloom_exports/folioloom-db-YYYYMMDD-HHMMSS.sql
```

If server credentials differ from the default user/database, use the values
from `.env`.

6. Start full stack and run checks:

```bash
docker compose up -d --build
scripts/server_smoke_check.sh
ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS=1 scripts/server_smoke_check.sh
scripts/server_status.sh
```

The strict `ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS=1` mode proves that restored
admin-managed provider keys are visible to `bot` and `worker`; internally the
smoke check passes `--require-admin-provider-keys` to the admin deployment
probe for runtime containers.

## Acceptance Criteria

- `scripts/verify_backup_export.py` passes.
- `docker compose ps` shows services running and healthchecks become healthy.
- `scripts/server_smoke_check.sh` passes.
- `ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS=1 scripts/server_smoke_check.sh` passes
  after provider keys are expected to be restored.
- `scripts/server_status.sh` shows available disk space and no recent bot or
  worker tracebacks.
- Existing translated files that are still within retention policy are
  available from My Books/history.
- `/admin/ai-providers` shows restored provider rows.
- Provider runtime status updates after manual provider reload.
- No restore step requires raw document text in logs/admin.

## If Restore Fails

Do not delete failed restore files. Capture diagnostics:

```bash
docker compose ps
docker compose logs --tail=200 postgres
docker compose logs --tail=200 bot
docker compose logs --tail=200 worker
scripts/server_status.sh
```

Then restore the saved `var.before-restore-*` directory or redeploy from the
last known good server snapshot.
