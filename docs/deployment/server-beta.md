# Server Beta Deployment

## Purpose

This runbook starts the closed beta backend with a Telegram bot, FastAPI health
endpoint, durable worker, PostgreSQL, and persistent local object storage.

The Telegram bot only accepts uploads and queues confirmed jobs. The worker
translates persisted work units. PostgreSQL and object storage keep progress
safe across Ctrl+C, process crashes, server restarts, and worker reconnects.

## First Setup

Copy the environment template:

```bash
cp .env.example .env
```

Fill these values in `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=replace-with-beta-bot-token
DEEPSEEK_API_KEY=replace-with-deepseek-key
POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator
JOB_STORE_BACKEND=postgres
TRANSLATION_EXECUTION_MODE=worker
OBJECT_STORAGE_ROOT=/data/object-storage
WORK_UNIT_LEASE_SECONDS=900
```

Start the stack in detached mode:

```bash
docker compose up -d --build
```

Check service health:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Expected responses:

```json
{"service":"FolioLoom","status":"ok"}
```

```json
{"service":"FolioLoom","status":"ready","object_storage":"ok","job_store":"ok"}
```

## Daily Operation

Show running services:

```bash
docker compose ps
```

Watch bot logs:

```bash
docker compose logs -f bot
```

Watch worker logs:

```bash
docker compose logs -f worker
```

Watch API logs:

```bash
docker compose logs -f api
```

Restart one service:

```bash
docker compose restart worker
```

Stop everything while keeping data volumes:

```bash
docker compose down
```

## Crash And Resume Behavior

- If the Telegram bot stops, queued jobs remain in PostgreSQL.
- If the worker stops during a fragment, completed fragments remain saved.
- The active fragment becomes claimable again after `WORK_UNIT_LEASE_SECONDS`.
- If the server restarts, Docker starts services again via `restart: unless-stopped`.
- Users can resume interrupted jobs because ownership, job status, work units,
  and output object keys are persisted.
- Users can download a fresh partial result from the currently translated work
  units instead of paying again after a failed attempt.

## Local Development Compose

For local config checks with development env values:

```bash
cp .env.dev.example .env.dev
docker compose -f docker-compose.yml -f docker-compose.local.yml config
```

For production-like server config checks:

```bash
cp .env.example .env
docker compose config
```

## Backup

Back up PostgreSQL:

```bash
docker compose exec postgres pg_dump -U translator translator > translator-backup.sql
```

Back up object storage:

```bash
docker run --rm \
  -v newproject2_object-storage:/data/object-storage \
  -v "$PWD":/backup \
  alpine tar czf /backup/object-storage-backup.tgz /data/object-storage
```

## Restore

Restore PostgreSQL:

```bash
docker compose exec -T postgres psql -U translator translator < translator-backup.sql
```

Restore object storage:

```bash
docker run --rm \
  -v newproject2_object-storage:/data/object-storage \
  -v "$PWD":/backup \
  alpine tar xzf /backup/object-storage-backup.tgz -C /
```

## Useful Failure Checks

If uploads work but translations do not start:

```bash
docker compose logs --tail=200 worker
docker compose exec postgres psql -U translator translator -c "select id, status, file_name, updated_at from translation_jobs order by created_at desc limit 10;"
```

If the bot answers but files are missing:

```bash
docker compose logs --tail=200 bot
docker compose exec api python -m translator_service.api
curl http://localhost:8000/ready
```

If the worker repeatedly retries the same fragment, check the provider error:

```bash
docker compose exec postgres psql -U translator translator -c "select id, job_id, status, retry_count, last_error from work_units where status = 'failed' order by updated_at desc limit 10;"
```
