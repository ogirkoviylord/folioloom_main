# Server Beta Deployment

> Status: Historical / superseded. This document is kept only to avoid broken
> links from older notes. Use `docs/deployment/admin-vps-runbook.md`,
> `docs/deployment/restore-runbook.md` and
> `docs/restart/folioloom-restart-spec.md` for the current closed-beta model.

The previous version of this runbook described an older beta deployment model
with stale env filenames, public port assumptions and Docker volume names. The
current deployment reality is:

- env example: `.env.server.example`;
- services: `api`, `bot`, `worker`, `postgres`, `redis`;
- admin/API bind: `127.0.0.1:62062 -> api:8000`;
- runtime mounts for app containers: `./var -> /app/var` and `./var -> /data`;
- Postgres data volume: `postgres-data`;
- admin access: SSH tunnel only;
- deployment command: `scripts/deploy_server.sh`;
- server smoke: `scripts/server_smoke_check.sh`;
- backup: `python3 scripts/backup_server_data.py --output-dir ~/folioloom_exports`;
- verification: `python3 scripts/verify_backup_export.py <manifest>`.

Do not use this file as an operational runbook.
