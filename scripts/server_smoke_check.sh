#!/usr/bin/env sh
set -eu

if [ ! -f ".env" ]; then
  echo "Missing .env. Create it from .env.server.example before smoke check." >&2
  exit 2
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

if [ "${SCHEDULER_BACKEND:-}" != "postgres" ]; then
  echo "SCHEDULER_BACKEND must be postgres on the server." >&2
  exit 2
fi

if [ "${REQUIRE_UPLOAD_SCAN:-false}" = "true" ] && [ "${UPLOAD_SCANNER_BACKEND:-}" != "clamd" ]; then
  echo "REQUIRE_UPLOAD_SCAN=true requires UPLOAD_SCANNER_BACKEND=clamd on the server." >&2
  exit 2
fi

if [ "${POSTGRES_PASSWORD:-}" = "translator" ]; then
  echo "POSTGRES_PASSWORD=translator is the example default; set a unique server password." >&2
  exit 2
fi

case "${POSTGRES_DSN:-${DATABASE_URL:-}}" in
  *translator:translator@*)
    echo "POSTGRES_DSN/DATABASE_URL still contains the example translator:translator credentials." >&2
    exit 2
    ;;
  postgresql://*@postgres:5432/*|postgres://*@postgres:5432/*) ;;
  *)
    echo "POSTGRES_DSN or DATABASE_URL must point to the compose postgres service." >&2
    exit 2
    ;;
esac

if [ ! -d "var" ]; then
  echo "Creating host runtime directory: var" >&2
  mkdir -p var
fi

docker compose config >/dev/null
docker compose ps
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-translator}" -d "${POSTGRES_DB:-translator}"
docker compose exec -T bot python -m compileall -q /app/src
admin_smoke_args="--require-existing-admin-db"
if [ "${ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS:-0}" = "1" ]; then
  admin_smoke_args="$admin_smoke_args --require-admin-provider-keys"
fi
docker compose exec -T api python -m translator_service.admin.deployment_smoke
docker compose exec -T bot python -m translator_service.admin.deployment_smoke $admin_smoke_args
set -- \
  --host "${CLAMD_HOST:-clamd}" \
  --port "${CLAMD_PORT:-3310}" \
  --timeout "${CLAMD_TIMEOUT_SECONDS:-10.0}" \
  --response-limit-bytes "${CLAMD_RESPONSE_LIMIT_BYTES:-4096}"
if [ "${REQUIRE_UPLOAD_SCAN:-false}" = "true" ]; then
  set -- "$@" --scan-eicar
fi
docker compose exec -T bot python -m translator_service.clamd_runtime "$@"
docker compose exec -T worker python -m translator_service.admin.deployment_smoke $admin_smoke_args
python3 scripts/backup_server_data.py --help >/dev/null

echo "Server smoke check passed."
