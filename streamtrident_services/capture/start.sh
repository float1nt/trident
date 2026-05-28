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
  echo "config file not found: capture/$ENV_FILE"
  echo "create it from capture/.env.example"
  exit 2
fi

export SURICATA_IFACE="${SURICATA_IFACE:-eth0}"
export REDIS_HOST_PORT="${REDIS_HOST_PORT:-16379}"
export SURICATA_AGENT_HOST_PORT="${SURICATA_AGENT_HOST_PORT:-19100}"

docker compose --env-file "$ENV_FILE" -f compose.yaml up -d --build redis redis-admin suricata-agent suricata-cic

cat <<EOF
capture stack started
  iface: $SURICATA_IFACE
  redis: 0.0.0.0:$REDIS_HOST_PORT
  suricata-agent: 0.0.0.0:$SURICATA_AGENT_HOST_PORT
EOF
