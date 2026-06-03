#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

if [ "$#" -gt 0 ]; then
  "${SCRIPT_DIR}/install.sh" "$1"
else
  "${SCRIPT_DIR}/install.sh"
fi

prepare_runtime

docker compose -f "${RUNTIME_DIR}/capture/compose.yaml" down
docker compose -f "${RUNTIME_DIR}/capture/compose.yaml" up -d --force-recreate

echo "Capture side updated."
echo "Redis: ${CAPTURE_HOST:-127.0.0.1}:${REDIS_HOST_PORT:-16379}"
echo "Suricata agent: http://${CAPTURE_HOST:-127.0.0.1}:${SURICATA_AGENT_HOST_PORT:-19100}"
