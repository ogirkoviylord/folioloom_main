#!/usr/bin/env sh
set -eu

if [ ! -f ".env" ]; then
  echo "Missing .env. Create it from .env.server.example before deploying." >&2
  exit 2
fi

git pull --ff-only
docker compose up -d --build
scripts/server_smoke_check.sh
docker compose logs --tail=50 bot
