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

if [ -f "${RUNTIME_DIR}/ui/compose.yaml" ]; then
  docker compose -f "${RUNTIME_DIR}/ui/compose.yaml" down
fi
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" down

docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up -d --force-recreate
docker compose -f "${RUNTIME_DIR}/ui/compose.yaml" up -d --force-recreate

echo "Analysis side and UI updated."
echo "Worker mode: ${TRIDENT_WORKER_MODE:-cold_start}"
echo "UI: http://127.0.0.1:${UI_HOST_PORT:-8088}"
echo "UI container: ${UI_CONTAINER_NAME:-streamtrident-ui}"
echo "Trident API: http://127.0.0.1:${TRIDENT_API_HOST_PORT:-8090}"
