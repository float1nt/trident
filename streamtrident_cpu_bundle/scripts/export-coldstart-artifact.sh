#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

load_deploy_env
prepare_runtime

SESSION_ID="${1:-accuracy-mixed_attack_panel-aa2b640d82}"
OUTPUT_NAME="${2:-coldstart-${SESSION_ID}.tar.gz}"
HOST_OUTPUT="${RUNTIME_DIR}/analysis/trident/artifacts/${OUTPUT_NAME}"
CONTAINER_OUTPUT="/var/lib/trident/artifacts/${OUTPUT_NAME}"

docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up -d clickhouse postgres trident-migrate
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" run --rm trident-tools \
  python -m app.coldstart_artifact export \
    --config config/trident.yaml \
    --session-id "${SESSION_ID}" \
    --output "${CONTAINER_OUTPUT}"

echo "Cold-start artifact exported: ${HOST_OUTPUT}"
