#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

prepare_runtime
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up -d
echo "Analysis started. Worker mode: ${TRIDENT_WORKER_MODE:-cold_start}"
