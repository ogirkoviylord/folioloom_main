# FolioLoom

Telegram bot prototype for translating books, chapters, and manuscripts.

FolioLoom is the Telegram product for the Folio & Loom translation workflow.
DeepSeek is an internal translation provider, not the user-facing brand.

## Current Prototype

Implemented:

- TXT upload validation and translation flow.
- DOCX text extraction, price estimation, and translation flow.
- EPUB text extraction, price estimation, and translation flow.
- DeepSeek chat-completions client.
- Fragmented TXT, DOCX, and EPUB translation runners.
- In-memory translation job status model.
- In-memory balance, ledger, order charge, and refund backend domain.
- aiogram runtime skeleton with `/start`, `/menu`, `/help`, `/language`, document upload, `/confirm`, `/cancel`, and `/status`.

The Telegram runtime currently translates TXT, DOCX, and EPUB files.

## Workspace Policy

Active development work must happen in the dev workspace:

```text
/path/to/local-workspace/Documents/New project 2 dev
```

The release workspace is reserved for the stable bot and must receive only reviewed, working changes ready for release:

```text
/path/to/local-workspace/Documents/New project 2
```

The legacy beta workspace must not be used for new development or updates:

```text
/path/to/local-workspace/Documents/New project 2 beta
```

Before changing files, confirm that the current working directory is the dev workspace unless the task explicitly says to prepare a release.

## Local Checks

Run from the project root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
```

## DeepSeek Smoke Test

```bash
DEEPSEEK_API_KEY='your_key' PYTHONPATH=src python3 -m translator_service.deepseek_probe
```

## DeepSeek API Channels

For local development with one API key, keep using:

```bash
DEEPSEEK_API_KEY='your_key'
```

For multiple internal API channels, provide a comma-separated key list:

```bash
DEEPSEEK_API_KEYS='key_one,key_two,key_three' \
DEEPSEEK_MAX_PARALLEL_PER_KEY='1' \
DEEPSEEK_CHANNEL_COOLDOWN_SECONDS='30' \
DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS='300' \
DEEPSEEK_CHANNEL_WEIGHTS='1,1,1'
```

The bot treats these keys as internal reliability channels. Users do not see or choose provider channels. Repeated keys are ignored after their first occurrence, and invalid weights fall back to `1` for every channel.

## Scheduler Runtime

The production scheduler is PostgreSQL-first. `SCHEDULER_BACKEND=sqlite` keeps
local development on the SQLite adapter; `SCHEDULER_BACKEND=postgres` uses the
psycopg-backed repository and the same scheduler contract.

Useful settings:

- `SCHEDULER_LEASE_SECONDS`: claim lease duration for one work unit.
- `SCHEDULER_POLL_SECONDS`: worker sleep interval when no work is due.
- `SCHEDULER_RETRY_BASE_DELAY_SECONDS`: first retry backoff.
- `SCHEDULER_RETRY_MAX_DELAY_SECONDS`: maximum retry backoff.
- `POSTGRES_DSN`: PostgreSQL connection string for production scheduler state.

Redis is not required for scheduler correctness. If a notification layer is
added, workers must still be able to recover by scanning due PostgreSQL rows.

## Server Deployment

Prepare server settings once:

```bash
cp .env.server.example .env
nano .env
```

Fill at least:

- `TELEGRAM_BOT_TOKEN`
- `DEEPSEEK_API_KEY` or `DEEPSEEK_API_KEYS`
- admin secrets if the admin console is enabled

Start or update the server:

```bash
scripts/deploy_server.sh
```

Before promoting changes to the server branch, run:

```bash
scripts/predeploy_check.sh
```

Runtime files are mounted from the host into containers:

```text
./var -> /app/var
```

This keeps uploaded files, translated files, SQLite fallback files, admin data,
and translation logs outside the container image. The `var/` directory is
ignored by git and should be included in server backups.

Run a quick server check after deployment:

```bash
scripts/server_smoke_check.sh
```

Inspect server state during beta testing:

```bash
scripts/server_status.sh
```

Restore rehearsal instructions are in `docs/deployment/restore-runbook.md`.

## Server Backups

Run this from the project root on the server:

```bash
python3 scripts/backup_server_data.py --output-dir ~/folioloom_exports
```

The script creates three files:

- `folioloom-db-YYYYMMDD-HHMMSS.sql`: PostgreSQL dump.
- `folioloom-files-YYYYMMDD-HHMMSS.tgz`: uploaded, intermediate, partial, and final files from `OBJECT_STORAGE_ROOT`.
- `folioloom-backup-YYYYMMDD-HHMMSS.manifest.json`: row counts, file counts, sizes, and SHA-256 hashes.

By default, the script refuses a suspicious backup where object storage contains files but the database has no `translation_jobs` rows. Use `--allow-empty-database` only for a deliberately empty test server.

Verify a downloaded backup manifest:

```bash
python3 scripts/verify_backup_export.py ~/Downloads/folioloom-backup-YYYYMMDD-HHMMSS.manifest.json
```

Download the latest backup to the Mac with:

```bash
scp 'ubuntu@YOUR_VPS_IP:~/folioloom_exports/folioloom-*' ~/Downloads/
```

## TXT Translation Probe

```bash
DEEPSEEK_API_KEY='your_key' PYTHONPATH=src python3 -m translator_service.translate_txt_probe
```

This writes `sample.en.txt` in the project root.

## Telegram Bot Prototype

Install dependencies first, preferably in a virtual environment:

```bash
python3 -m pip install -e .
```

Then run:

```bash
TELEGRAM_BOT_TOKEN='your_bot_token' \
DEEPSEEK_API_KEY='your_deepseek_key' \
PYTHONPATH=src \
python3 -m translator_service.bot
```

When startup succeeds, the terminal prints:

```text
Telegram bot polling started. Open Telegram and send /start.
```

Prototype flow:

1. Send `/start`.
2. Choose `📖 Translate a Book`, or use `🌍 Language` to change the interface language.
3. Upload a `.txt`, `.docx`, or `.epub` file.
4. Choose the translation target language button.
5. Review the estimate and translation summary.
6. Press the localized start button or send `/confirm`.
   Use the localized Back button before confirmation if the wrong file was uploaded.
7. The bot returns the translated file.

During long translations, press the localized Cancel button or send `/cancel` to stop after the current fragment and receive a partial translated file.

Use `/menu` to return to the main menu, `/help` for the help screen, and `/language` to show the interface language buttons again.

Interface messages are currently localized for English, Russian, Ukrainian, French, Spanish, and Dutch.

Sample documents for manual dev checks are in `test_samples/`. Regenerate them with:

```bash
python3 scripts/generate_sample_documents.py
```

For auto-restart during development:

```bash
TELEGRAM_BOT_TOKEN='your_bot_token' \
DEEPSEEK_API_KEY='your_deepseek_key' \
PYTHONPATH=src \
watchfiles "python3 -m translator_service.bot" src
```

## Stable and Dev Bots

Use two different Telegram bots from BotFather:

- stable bot: for the version users rely on;
- dev bot: for testing new behavior from the dev workspace.

Each bot must have its own `TELEGRAM_BOT_TOKEN`. Never run two polling
processes with the same token.

Create local env files from the examples:

```bash
cp .env.stable.example .env.stable
cp .env.dev.example .env.dev
```

Fill `.env.stable` with the stable bot token and `.env.dev` with the dev bot
token. These local files are ignored by git.

Run the stable bot in one terminal:

```bash
scripts/run_bot_env.sh .env.stable
```

Run the dev bot in another terminal:

```bash
scripts/run_bot_env.sh .env.dev
```

During development, you can run the dev bot with auto-restart:

```bash
set -a
source .env.dev
set +a
PYTHONPATH=src watchfiles "python3 -m translator_service.bot" src
```

For production later, stable and dev must also use separate databases, queues,
storage buckets, payment keys, and admin settings.

## Clean-Room Note

This project is implemented from scratch. Do not copy AGPL code, prompts, file structure, class/function names, tests, or implementation details from AGPL projects.
