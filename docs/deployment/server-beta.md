# Server Beta Deployment

This is the OVH/VPS runbook for running the `main` branch as the first closed
beta. The stack runs the Telegram bot, FastAPI admin/health app, background
worker, PostgreSQL scheduler store, persistent object storage, runtime state,
and translation run logs.

## First Setup

Install Docker and clone or copy the project to the server. From the project
directory:

```bash
cp .env.example .env
```

Fill at least these values in `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=replace-with-main-bot-token
DEEPSEEK_API_KEY=replace-with-deepseek-key
SCHEDULER_BACKEND=postgres
POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator
OBJECT_STORAGE_ROOT=/data/object-storage
USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3
TRANSLATION_RUN_LOG_ROOT=/data/run-logs
```

Start the stack:

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
curl http://localhost:8000/health
```

Expected health payload:

```json
{"service":"FolioLoom","status":"ok"}
```

## Daily Operation

Watch logs:

```bash
docker compose logs -f bot
docker compose logs -f worker
docker compose logs -f api
```

Restart one service:

```bash
docker compose restart worker
```

Stop services while keeping data:

```bash
docker compose down
```

## Persistence

The important data lives in Docker volumes:

- `postgres-data`: scheduler jobs, work units, attempts, worker heartbeats.
- `object-storage`: uploaded originals, partial files, finished files.
- `runtime-data`: local SQLite runtime/admin/user settings files.
- `run-logs`: translation run logs and provider/token summaries.

The compose file does not expose PostgreSQL to the public internet. Only the
API port `8000` is published by default.

## Backups

Back up PostgreSQL:

```bash
docker compose exec postgres pg_dump -U translator translator > translator-backup.sql
```

Back up stored files:

```bash
docker run --rm \
  -v newproject2_object-storage:/data/object-storage \
  -v "$PWD":/backup \
  alpine tar czf /backup/object-storage-backup.tgz /data/object-storage
```

Back up runtime state and run logs:

```bash
docker run --rm \
  -v newproject2_runtime-data:/data/runtime \
  -v newproject2_run-logs:/data/run-logs \
  -v "$PWD":/backup \
  alpine tar czf /backup/runtime-backup.tgz /data/runtime /data/run-logs
```

## Failure Checks

If the bot answers but translation does not move:

```bash
docker compose logs --tail=200 worker
docker compose logs --tail=200 bot
```

If the API is reachable but admin/health looks wrong:

```bash
docker compose logs --tail=200 api
curl http://localhost:8000/health
```

If PostgreSQL jobs need inspection:

```bash
docker compose exec postgres psql -U translator translator -c "select id, status, file_name, updated_at from translation_jobs order by created_at desc limit 10;"
docker compose exec postgres psql -U translator translator -c "select id, job_id, status, attempt_count, last_error from work_units order by updated_at desc limit 10;"
```
