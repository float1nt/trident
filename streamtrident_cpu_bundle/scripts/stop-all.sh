#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

for file in \
  "${RUNTIME_DIR}/ui/compose.yaml" \
  "${RUNTIME_DIR}/analysis/compose.yaml" \
  "${RUNTIME_DIR}/capture/compose.yaml"; do
  if [ -f "${file}" ]; then
    docker compose -f "${file}" down
  fi
done
