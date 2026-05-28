#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE="${ENV_FILE:-.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "config file not found: analysis/$ENV_FILE"
  echo "create it from analysis/.env.example"
  exit 2
fi

export CAPTURE_REDIS_HOST="${CAPTURE_REDIS_HOST:-host.docker.internal}"
export CAPTURE_REDIS_PORT="${CAPTURE_REDIS_PORT:-16379}"
export TRIDENT_SURICATA_AGENT_URLS="${TRIDENT_SURICATA_AGENT_URLS:-http://host.docker.internal:19100}"
export TRIDENT_API_HOST_PORT="${TRIDENT_API_HOST_PORT:-8090}"

docker compose --env-file "$ENV_FILE" -f compose.yaml up -d --build clickhouse postgres trident-migrate trident-worker trident-api

cat <<EOF
trident stack started
  api: 0.0.0.0:$TRIDENT_API_HOST_PORT
  capture redis: $CAPTURE_REDIS_HOST:$CAPTURE_REDIS_PORT
  suricata agents: $TRIDENT_SURICATA_AGENT_URLS
EOF
