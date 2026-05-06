#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/run_bot_env.sh .env.dev|.env.stable" >&2
  exit 2
fi

ENV_FILE="$1"

if [ ! -f "$ENV_FILE" ]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export PYTHONPATH="${PYTHONPATH:-src}"

python3 -m translator_service.bot
