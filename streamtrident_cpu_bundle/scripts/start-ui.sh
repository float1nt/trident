#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

prepare_runtime
docker compose -f "${RUNTIME_DIR}/ui/compose.yaml" up -d
echo "UI: http://127.0.0.1:${UI_HOST_PORT:-8088}"
