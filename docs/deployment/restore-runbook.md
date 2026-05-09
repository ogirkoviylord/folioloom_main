# FolioLoom Restore Runbook

This runbook rehearses recovery from a FolioLoom backup created by
`scripts/backup_server_data.py`.

Use it before the first public beta and after any storage or database change.

## Inputs

You need the three files from one backup timestamp:

```text
folioloom-db-YYYYMMDD-HHMMSS.sql
folioloom-files-YYYYMMDD-HHMMSS.tgz
folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

You also need the same `ADMIN_SECRET_MASTER_KEY` that encrypted the backed-up
`admin.sqlite3`. Store it separately from the backup archive.

Verify the backup before restoring:

```bash
python3 scripts/verify_backup_export.py ~/folioloom_exports/folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

## Restore Rehearsal On A Fresh Server Copy

Do this on a test server or a disposable copy first.

1. Stop FolioLoom:

```bash
docker compose down
```

2. Keep a local copy of the current runtime directory if it exists:

```bash
mv var "var.before-restore-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
mkdir -p var
```

3. Restore object storage and runtime files:

```bash
tar xzf ~/folioloom_exports/folioloom-files-YYYYMMDD-HHMMSS.tgz
```

The archive should recreate the host `var/` runtime tree. With the production
`/data/...` container paths, this usually means `var/object-storage` and
`var/runtime/admin.sqlite3` on the VPS host.

4. Start only the database:

```bash
docker compose up -d postgres
```

5. Recreate the database contents:

```bash
docker compose exec -T postgres psql -U translator -d translator -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T postgres psql -U translator -d translator < ~/folioloom_exports/folioloom-db-YYYYMMDD-HHMMSS.sql
```

6. Start the full stack:

```bash
docker compose up -d --build
scripts/server_smoke_check.sh
ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS=1 scripts/server_smoke_check.sh
scripts/server_status.sh
```

The `ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS=1` mode makes the smoke check run the
admin deployment probe with `--require-admin-provider-keys`, so a restored admin
database without active provider keys fails loudly.

## Acceptance Criteria

- `scripts/verify_backup_export.py` passes.
- `docker compose ps` shows services running, and backend healthchecks become healthy.
- `scripts/server_smoke_check.sh` passes.
- `scripts/server_status.sh` shows available disk space and no recent bot or worker tracebacks.
- Existing translated files are available from the bot's “My books” flow.
- `/admin/ai-providers` shows the restored provider rows and the bot runtime
  status updates after a manual provider reload.

## If Restore Fails

Do not delete the failed restore files. Capture:

```bash
docker compose ps
docker compose logs --tail=200 postgres
docker compose logs --tail=200 bot
docker compose logs --tail=200 worker
scripts/server_status.sh
```

Then restore the saved `var.before-restore-*` directory or redeploy from the
last known good server snapshot.
