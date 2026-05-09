#!/usr/bin/env sh
set -eu

echo "== FolioLoom predeploy check =="

if [ ! -f ".env.server.example" ]; then
  echo "Missing .env.server.example" >&2
  exit 2
fi

if grep -Eq "(sk-[A-Za-z0-9]{16,}|[0-9]{8,}:[A-Za-z0-9_-]{20,})" .env.server.example; then
  echo ".env.server.example appears to contain a real secret." >&2
  exit 2
fi

echo "== Compose config =="
docker compose --env-file .env.server.example config >/dev/null

echo "== Server hardening tests =="
PYTHONPATH=src python3 -m unittest \
  tests.test_server_deployment_config \
  tests.test_backup_server_data \
  tests.test_admin_deployment_smoke \
  tests.test_admin_translation_logs \
  tests.test_config \
  tests.test_bot_runtime.BotRuntimeTest.test_admin_deepseek_translator_adds_admin_without_dropping_env

echo "== Lint =="
python3 -m ruff check \
  src/translator_service/admin/deployment_smoke.py \
  src/translator_service/bot/runtime.py \
  src/translator_service/config.py \
  scripts/backup_server_data.py \
  tests/test_admin_deployment_smoke.py \
  tests/test_backup_server_data.py \
  tests/test_server_deployment_config.py \
  tests/test_bot_runtime.py

echo "== CLI smoke =="
python3 scripts/backup_server_data.py --help >/dev/null
PYTHONPATH=src python3 -m translator_service.admin.deployment_smoke --help >/dev/null
python3 scripts/verify_backup_export.py --help >/dev/null

echo "== Shell syntax =="
sh -n \
  scripts/deploy_server.sh \
  scripts/predeploy_check.sh \
  scripts/server_smoke_check.sh \
  scripts/server_status.sh

echo "== Documentation check =="
grep -q "scripts/deploy_server.sh" README.md
grep -q "scripts/server_smoke_check.sh" README.md
grep -q "scripts/server_status.sh" README.md
grep -q "scripts/verify_backup_export.py" README.md
grep -q "docker compose exec -T postgres psql" docs/deployment/restore-runbook.md

echo "== Compile =="
PYTHONPATH=src python3 -m compileall \
  scripts/backup_server_data.py \
  scripts/verify_backup_export.py \
  src >/dev/null

echo "== Diff hygiene =="
git diff --check -- \
  docker-compose.yml \
  .env.server.example \
  README.md \
  docs/deployment/restore-runbook.md \
  docs/deployment/admin-vps-runbook.md \
  scripts/backup_server_data.py \
  scripts/deploy_server.sh \
  scripts/predeploy_check.sh \
  scripts/server_smoke_check.sh \
  scripts/server_status.sh \
  scripts/verify_backup_export.py \
  src/translator_service/admin/deployment_smoke.py \
  src/translator_service/bot/runtime.py \
  src/translator_service/config.py \
  tests/test_admin_deployment_smoke.py \
  tests/test_backup_server_data.py \
  tests/test_bot_runtime.py \
  tests/test_server_deployment_config.py

echo "Predeploy check passed."
