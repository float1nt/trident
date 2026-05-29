#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE="${ENV_FILE:-.env.test}"
COMPOSE_FILES=(-f compose.yaml -f compose.test.yaml)

if [ ! -f "$ENV_FILE" ]; then
  echo "config file not found: analysis/$ENV_FILE"
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export CAPTURE_REDIS_HOST="${CAPTURE_REDIS_HOST:-host.docker.internal}"
export CAPTURE_REDIS_PORT="${CAPTURE_REDIS_PORT:-16379}"
export TRIDENT_SURICATA_AGENT_URLS="${TRIDENT_SURICATA_AGENT_URLS:-http://host.docker.internal:19100}"
export TRIDENT_API_HOST_PORT="${TRIDENT_API_HOST_PORT:-9090}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-streamtrident-test}"

mkdir -p ./trident/logs-test

docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" up -d --build \
  clickhouse postgres trident-migrate trident-worker trident-api

cat <<EOF
trident test stack started (project: $COMPOSE_PROJECT_NAME)
  api:        0.0.0.0:$TRIDENT_API_HOST_PORT
  postgres:   0.0.0.0:${POSTGRES_HOST_PORT:-25432}
  clickhouse: 0.0.0.0:${CLICKHOUSE_HTTP_HOST_PORT:-28123} (http), 0.0.0.0:${CLICKHOUSE_NATIVE_HOST_PORT:-29000} (native)
  capture redis: $CAPTURE_REDIS_HOST:$CAPTURE_REDIS_PORT
  suricata agents: $TRIDENT_SURICATA_AGENT_URLS
  stop: ./stop-test.sh
EOF
