# FolioLoom

FolioLoom - CAT-like author/rightsholder translation workbench для авторизованных длинных документов: книг, глав, рукописей, редакторских материалов, public-domain текстов и документов, на которые у пользователя есть права.

Telegram-бот остаётся удобным upload/test/delivery harness, но больше не является определяющей продуктовой поверхностью или release compass. Canonical strategy issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813). Canonical gate doc: `docs/CAT_WORKFLOW_GATES.md`.

DeepSeek-compatible APIs - внутренний provider layer. Пользовательский бренд и
UX остаются FolioLoom.

## Current Status

| Область | Статус |
| --- | --- |
| Product stage | CAT-like workflow reframe / active development |
| Следующий milestone | Gate 1 glossary/terminology control prototype |
| Paid launch | Blocked до quality/workflow/safety/payment evidence |
| Public production | Not ready |
| Форматы текущего scope | TXT, DOCX, EPUB |
| Primary surface | CAT-like author workflow TBD; Telegram is harness |
| Admin access | SSH tunnel only |
| Beta access control | Owner/trusted cohort; Telegram allowlist foundations exist |

Проект уже не является in-memory prototype. В репозитории есть persistent
jobs/work units, object storage, worker loop, admin console, Docker Compose
deployment, backup/restore workflow и широкий unittest suite.

## What FolioLoom Does

- Целевой workflow: import authorized TXT/DOCX/EPUB, preserve structure/segments,
  review/edit glossary, generate translation draft/suggestions, inspect QA
  findings and export a usable translated document.
- Telegram remains a harness for upload/test/delivery where convenient.
- Поддерживает invite-only/trusted testing foundations via Telegram allowlist and
  owner/admin controls.
- Переводит TXT/DOCX/EPUB через DeepSeek-compatible provider.
- Хранит accepted documents, jobs, work units, partial/final results и runtime
  metadata в backend/object storage.
- Выполняет работу через background worker loop.
- Дает owner/admin visibility через FastAPI admin console.
- Поддерживает Docker Compose deploy на VPS.
- Имеет backup/restore scripts и restore runbook.

## Supported / Not Supported

| Supported foundations | Not supported / not ready |
| --- | --- |
| TXT/DOCX/EPUB import/translation foundations | Paid public SaaS |
| Telegram harness for upload/test/delivery | Payment UI or paid jobs |
| Manual/author glossary direction under #813 | Automatic glossary quality claim |
| Admin-managed allowlist/cost/kill-switch foundations | Public self-serve signup |
| DeepSeek-compatible internal providers | User-facing provider/model picker |
| Persistent jobs/work units | Arbitrary file parser |
| Local object storage on server runtime | Public object bucket/product portal |
| Worker loop and resumable backend foundations | Public admin exposure |
| Admin console through SSH tunnel | Subscriptions, referrals, coupons, teams |
| Backup/restore workflow | Stripe/YooKassa/card flow as immediate path |

Committed future formats:

- FolioLoom is committed to future support for RTF (#4), FB2
  ([#23](https://github.com/ogirkoviylord/folioloom_main/issues/23)), PDF/OCR,
  HTML/HTM, ODT, legacy DOC, MOBI, AZW3/KPF and CBZ/CBR/DJVU.
- These formats remain unsupported for the next beta. Issue #208 owns
  prioritization and issue breakdown before any format-specific implementation
  approval.

### Beta Safety / Cost Guard

FolioLoom keeps beta throughput bounded with a cost-aware safety layer:

- new persistent jobs use reservation-at-enqueue before queue execution;
- global and per-user cost caps are enforced at reservation time;
- completed work units record prompt/completion token usage idempotently;
- the scheduler stops claiming new units when the admin kill switch or global
  caps are active;
- Admin -> Costs, Admin -> Settings and Admin -> Live show consumed, reserved
  and remaining beta budget, cap warnings and live pause state;
- no raw document text, prompts, translations or API keys are stored in safety
  telemetry.

This layer is an operational beta guard, separate from paid beta billing.
Telegram Stars/XTR and a payment ledger remain a separate release gate.

## Source Of Truth

- `docs/CAT_WORKFLOW_GATES.md` - canonical CAT-like workflow gate model.
- `CURRENT_PROJECT_STATE.md` - фактическое состояние проекта.
- `DOCUMENT_INDEX.md` - карта активных и historical docs.
- `docs/restart/release-gates.md` - current checklists; old Gate B/C is superseded as primary compass.
- `docs/restart/real-file-test-matrix.md` - real-file corpus and QA matrix.
- `docs/restart/upload-safety-and-retention.md` - upload safety, quarantine,
  local malware scanning, TTL and retention rules.
- `docs/restart/folioloom-restart-spec.md` - historical restart spec / old product boundary; use #813 for current strategy.
- `docs/restart/two-week-engineering-plan.md` - historical/superseded old free-beta plan.

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
- `BETA_ALLOWLIST_ENABLED=false` and optional `BETA_ALLOWLIST_TELEGRAM_IDS`
  for bootstrap; the live allowlist is managed in SSH-tunneled admin settings
- `DEEPSEEK_API_KEY` or `DEEPSEEK_API_KEYS`
- `TRANSLATION_MAX_PARALLEL_UNITS` for worker-side scheduled work-unit capacity
- `POSTGRES_PASSWORD`
- `POSTGRES_DSN` / `DATABASE_URL`
- `ADMIN_OWNER_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `ADMIN_SECRET_MASTER_KEY`

For a small closed beta, keep conservative safety caps in `.env` bootstrap and
adjust the live values from Admin -> Settings after deploy:

- `BETA_GLOBAL_DAILY_COST_CAP_USD=5.00`
- `BETA_GLOBAL_MONTHLY_COST_CAP_USD=50.00`
- `BETA_USER_DAILY_COST_CAP_USD=1.00`
- `BETA_USER_DAILY_JOB_LIMIT=3`

`ADMIN_SECRET_MASTER_KEY` enables encrypted admin-managed secrets. DeepSeek
keys added in the admin UI are additive with `DEEPSEEK_API_KEY` /
`DEEPSEEK_API_KEYS`: adding an admin key does not disable env keys. The
SSH-tunneled `/admin/ai-providers` page can show and refresh the safe DeepSeek
account balance snapshot without exposing real keys.
Admin -> AI Providers -> DeepSeek Keys is the operator surface for key rotation
and capacity changes. Add or rotate a key there, test it, then request DeepSeek
runtime reload so bot and worker processes pick up the new key pool. Env keys
remain read-only fallbacks; admin-managed keys are stored encrypted and only
masked values are shown.

Worker parallelism is beta-safe and capacity-bound. The server example uses
`TRANSLATION_MAX_PARALLEL_UNITS=2`, but concurrency is layered:
`TRANSLATION_MAX_PARALLEL_UNITS` sets worker-side scheduled work-unit capacity,
provider capacity caps active DeepSeek calls by env/admin key count times each
key's `DEEPSEEK_MAX_PARALLEL_PER_KEY` or admin max-parallel setting, and
scheduler fairness caps keep one job/user from monopolizing available slots.
With one key at capacity 1, provider calls remain serial; with multiple free
keys, separate documents can progress concurrently.

The AI Providers admin page reports DeepSeek runtime channel health without
secrets or document text: active requests, per-key capacity, cooldown,
429/503/timeout/auth/billing counters, latency and a redacted last error. A
degraded channel does not disable the key automatically in Phase 2; it lowers
selection priority and remains visible for operator action.

Phase 3 adaptive provider throttling starts each runtime conservatively and
ramps DeepSeek concurrency after clean successes. 429/503/timeouts decrease the
local adaptive limit and cool down affected channels; auth/billing failures open
a provider circuit for the configured reset window. This is local per worker,
not a distributed global quota system.

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

Closed-beta allowlist management lives under:

```text
http://127.0.0.1:62062/admin/settings
```

The allowlist can be filled ahead of time. Enforcement remains off until the
owner presses `Enable allowlist`; when enabled, non-allowlisted Telegram users
receive an invite-only message and new uploads are not downloaded.

To pause all beta translations without restart, open Admin -> Settings and
enable `BETA_TRANSLATIONS_PAUSED`. New uploads/jobs are rejected safely and the
scheduler stops claiming new work while already recorded work-unit usage remains
idempotent.

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
| Gate 0 - Product reframe | Lock CAT-like author/rightsholder workbench direction | #813 and `docs/CAT_WORKFLOW_GATES.md` remain canonical |
| Gate 1 - Glossary control | Manual/author-approved terminology control improves representative outputs | Before/after quality evidence |
| Gate 2 - CAT workflow | Import, glossary review, translation draft, QA and export work end to end | Thin slice evidence |
| Gate 3 - Quality evidence | Representative metadata-only matrix separates structure, terminology and semantic quality | Reviewer/evidence report |
| Gate 4 - Design partner alpha | Small trusted cohort validates workflow value | Usable-draft and willingness-to-pay signal |
| Gate 5 - Operational safety | Old Gate B safety items carried forward around CAT workflow | Operational evidence / explicit deferrals |
| Gate 6 - Paid pilot | Limited paid jobs after value/quality/safety evidence | Support/refund/cost evidence |
| Gate 7 - Self-serve paid beta | Payment ledger/idempotency/refund/reconciliation are ready | Paid beta go/no-go |
| Gate 8 - Public production | Public hardening, support, legal/privacy and ops maturity | Production go/no-go |

See `docs/CAT_WORKFLOW_GATES.md` for the canonical strategy and `docs/restart/release-gates.md` for checklists.

## Caveats

- Do not present FolioLoom as a paid public production service yet.
- Do not treat old Gate B/C as the current product roadmap.
- Do not expose payment UI before quality/workflow evidence and the paid gates.
- Do not treat beta safety reservations or usage accounting as a paid ledger.
- Do not expand current formats beyond TXT/DOCX/EPUB.
- Do not expose admin publicly.
- Do not log or show raw document text in normal admin/run logs.
- Do not claim automatic glossary runtime quality from local/fake/provider-boundary evidence.
- Do not use global ruff cleanup as a release blocker.

## Clean-Room Note

This project is implemented from scratch. Do not copy AGPL code, prompts, file
structure, class/function names, tests, or implementation details from AGPL
projects.

## Repository content

This repository contains the FolioLoom implementation, tests and engineering
design history. Internal developer instructions, personal deployment records
and unverified external document packs are excluded from the public candidate.
See `test_samples/rights-manifest.json` for the provenance of committed
synthetic material. Full external books remain outside source history. No project source-code license has been selected
yet; repository visibility is not a blanket license for third-party material.
