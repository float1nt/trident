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

for file in \
  "${RUNTIME_DIR}/ui/compose.yaml" \
  "${RUNTIME_DIR}/analysis/compose.yaml" \
  "${RUNTIME_DIR}/capture/compose.yaml"; do
  if [ -f "${file}" ]; then
    docker compose -f "${file}" down
  fi
done

docker compose -f "${RUNTIME_DIR}/capture/compose.yaml" up -d --force-recreate
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up -d --force-recreate
docker compose -f "${RUNTIME_DIR}/ui/compose.yaml" up -d --force-recreate

echo "Local StreamTrident stack updated."
echo "UI: http://127.0.0.1:${UI_HOST_PORT:-8088}"
echo "UI container: ${UI_CONTAINER_NAME:-streamtrident-ui}"
echo "Trident API: http://127.0.0.1:${TRIDENT_API_HOST_PORT:-8090}"
