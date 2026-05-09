# FolioLoom

FolioLoom - Telegram-first сервис перевода авторизованных длинных документов:
книг, глав, рукописей, редакторских материалов, public-domain текстов и
документов, на которые у пользователя есть права.

DeepSeek-compatible APIs - внутренний provider layer. Пользовательский бренд и
UX остаются FolioLoom.

## Current Status

| Область | Статус |
| --- | --- |
| Product stage | Working closed-beta foundation |
| Следующий milestone | Free closed beta |
| Paid launch | Blocked до отдельного payment/readiness gate |
| Public production | Not ready |
| Форматы beta | TXT, DOCX, EPUB |
| Admin access | SSH tunnel only |

Проект уже не является in-memory prototype. В репозитории есть persistent
jobs/work units, object storage, worker loop, admin console, Docker Compose
deployment, backup/restore workflow и широкий unittest suite.

## What FolioLoom Does

- Принимает upload документов в Telegram и ведет пользователя через выбор
  языка, estimate, confirmation, progress, cancel/status/history flows.
- Переводит TXT/DOCX/EPUB через DeepSeek-compatible provider.
- Хранит accepted documents, jobs, work units, partial/final results и runtime
  metadata в backend/object storage.
- Выполняет работу через background worker loop.
- Дает owner/admin visibility через FastAPI admin console.
- Поддерживает Docker Compose deploy на VPS.
- Имеет backup/restore scripts и restore runbook.

## Supported / Not Supported

| Supported for beta foundation | Not supported for next beta |
| --- | --- |
| Telegram upload/translate flow | Paid public SaaS |
| TXT/DOCX/EPUB | PDF/OCR/MOBI/FB2/batch ZIP |
| DeepSeek-compatible internal providers | User-facing provider/model picker |
| Persistent jobs/work units | Arbitrary file parser |
| Local object storage on server runtime | Public object bucket/product portal |
| Worker loop and resumable backend foundations | Public admin exposure |
| Admin console through SSH tunnel | Subscriptions, referrals, coupons, teams |
| Backup/restore workflow | Stripe/YooKassa/card flow as immediate Telegram path |

## Source Of Truth

- `CURRENT_PROJECT_STATE.md` - фактическое состояние проекта.
- `DOCUMENT_INDEX.md` - карта активных и historical docs.
- `docs/restart/folioloom-restart-spec.md` - canonical restart-ТЗ.
- `docs/restart/release-gates.md` - release gates.
- `docs/restart/two-week-engineering-plan.md` - ближайший engineering plan.
- `docs/restart/real-file-test-matrix.md` - real-file corpus and QA matrix.
- `docs/restart/upload-safety-and-retention.md` - upload safety, quarantine,
  TTL and retention rules.

## Verification Commands

Run from repo root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

`scripts/predeploy_check.sh` is the current predeploy gate. It includes Docker
Compose config validation, focused server hardening tests, targeted lint, CLI
smoke checks, shell syntax checks, documentation checks, compile checks and
diff hygiene.

Repo-wide ruff cleanup is not a release blocker right now:

```bash
python3 -m ruff check --no-cache src tests scripts
```

That broader command still reports historical style/import/line-length debt.
Keep it as a debt sprint, not as a free closed-beta gate.

## Deployment Overview

Prepare server settings:

```bash
cp .env.server.example .env
nano .env
```

Required values include:

- `TELEGRAM_BOT_TOKEN`
- `DEEPSEEK_API_KEY` or `DEEPSEEK_API_KEYS`
- `POSTGRES_PASSWORD`
- `POSTGRES_DSN` / `DATABASE_URL`
- `ADMIN_OWNER_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `ADMIN_SECRET_MASTER_KEY`

Start or update the stack:

```bash
scripts/deploy_server.sh
```

Current Docker Compose services:

- `api` - FastAPI health/admin app, bound on VPS loopback as
  `127.0.0.1:62062 -> api:8000`;
- `bot` - aiogram Telegram runtime;
- `worker` - background translation worker;
- `postgres` - scheduler/job/work-unit state;
- `redis` - present for runtime integration/future notification paths, not the
  source of scheduler correctness.

Runtime files are mounted from the host into app containers:

```text
./var -> /app/var
./var -> /data
```

Production env paths should use `/data/...`, for example:

- `OBJECT_STORAGE_ROOT=/data/object-storage`
- `PERSISTENT_JOBS_DB_PATH=/data/runtime/jobs.sqlite3`
- `USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3`
- `TRANSLATION_RUN_LOG_ROOT=/data/run-logs`
- `ADMIN_DB_PATH=/data/runtime/admin.sqlite3`

PostgreSQL data lives in the Docker volume `postgres-data`.

Admin remains private:

```bash
ssh -L 62062:127.0.0.1:62062 user@YOUR_VPS_IP
```

Then open:

```text
http://127.0.0.1:62062/admin/live
```

After deploy:

```bash
scripts/server_smoke_check.sh
scripts/server_status.sh
```

## Backup And Restore

Create a server backup:

```bash
python3 scripts/backup_server_data.py --output-dir ~/folioloom_exports
```

The backup includes a PostgreSQL dump, a runtime/files archive and a manifest.
Verify the manifest:

```bash
python3 scripts/verify_backup_export.py ~/folioloom_exports/folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

Restore rehearsal instructions are in `docs/deployment/restore-runbook.md`.
Keep `ADMIN_SECRET_MASTER_KEY` outside the backup bundle. Without the same key,
restored encrypted admin secrets cannot be decrypted.

## Local Development

Install dependencies in a virtual environment:

```bash
python3 -m pip install -e .
```

Run the bot locally:

```bash
TELEGRAM_BOT_TOKEN='your_bot_token' \
DEEPSEEK_API_KEY='your_deepseek_key' \
PYTHONPATH=src \
python3 -m translator_service.bot
```

DeepSeek probe:

```bash
DEEPSEEK_API_KEY='your_key' PYTHONPATH=src python3 -m translator_service.deepseek_probe
```

Generate sample documents:

```bash
python3 scripts/generate_sample_documents.py
```

Use different Telegram bots/tokens for stable and dev runtimes. Never run two
polling processes with the same token.

## Beta Roadmap Summary

| Stage | Goal | Exit condition |
| --- | --- | --- |
| Immediate stabilization | Docs, deployment consistency, allowlist/caps/rights/preview/safety baseline | Gate A |
| Free closed beta | Trusted users translate authorized real TXT/DOCX/EPUB files | Gate B |
| Paid beta | Telegram Stars/XTR payments and ledger are safe | Gate C |
| Public production | Public hardening, support, legal/privacy and ops maturity | Gate D |

See `docs/restart/release-gates.md` for the canonical checklists.

## Caveats

- Do not present FolioLoom as a paid public production service yet.
- Do not expose payment UI before the payment gate.
- Do not expand beta formats beyond TXT/DOCX/EPUB.
- Do not expose admin publicly in closed beta.
- Do not log or show raw document text in admin/run logs.
- Do not use global ruff cleanup as a release blocker.

## Clean-Room Note

This project is implemented from scratch. Do not copy AGPL code, prompts, file
structure, class/function names, tests, or implementation details from AGPL
projects.
