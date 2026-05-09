#!/usr/bin/env sh
set -eu

echo "== FolioLoom server status =="
date

echo
echo "== Containers =="
docker compose ps

echo
echo "== Disk =="
df -h .

echo
echo "== Runtime data size =="
if [ -d "var" ]; then
  du -sh var
  find var -maxdepth 2 -type d -print
else
  echo "var directory is missing"
fi

echo
echo "== Latest backups =="
if [ -d "$HOME/folioloom_exports" ]; then
  find "$HOME/folioloom_exports" -maxdepth 1 -type f -name 'folioloom-*' -print | sort | tail -20
else
  echo "No folioloom_exports directory found"
fi

echo
echo "== Recent bot errors =="
docker compose logs --tail=200 bot 2>/dev/null | grep -Ei "error|exception|failed|traceback" || echo "No recent bot errors found"

echo
echo "== Recent worker errors =="
docker compose logs --tail=200 worker 2>/dev/null | grep -Ei "error|exception|failed|traceback" || echo "No recent worker errors found"

echo
echo "== Postgres readiness =="
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-translator}" -d "${POSTGRES_DB:-translator}"
