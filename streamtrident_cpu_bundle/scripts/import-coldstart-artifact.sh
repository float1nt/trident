#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

load_deploy_env
prepare_runtime

ARTIFACT_PATH="${1:-}"
TARGET_SESSION_ID="${2:-accuracy-mixed_attack_panel-aa2b640d82}"

if [ -z "${ARTIFACT_PATH}" ]; then
  echo "Usage: $0 <coldstart-artifact.tar.gz> [target-session-id]" >&2
  exit 2
fi

mkdir -p "${RUNTIME_DIR}/analysis/trident/artifacts"
ARTIFACT_NAME="$(basename "${ARTIFACT_PATH}")"
HOST_ARTIFACT="${RUNTIME_DIR}/analysis/trident/artifacts/${ARTIFACT_NAME}"
if [ "$(realpath -m "${ARTIFACT_PATH}")" != "$(realpath -m "${HOST_ARTIFACT}")" ]; then
  cp "${ARTIFACT_PATH}" "${HOST_ARTIFACT}"
fi
CONTAINER_ARTIFACT="/var/lib/trident/artifacts/${ARTIFACT_NAME}"

docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up -d clickhouse postgres trident-migrate
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" run --rm trident-tools \
  python -m app.coldstart_artifact import \
    --config config/trident.yaml \
    --artifact "${CONTAINER_ARTIFACT}" \
    --target-session-id "${TARGET_SESSION_ID}"

echo "Cold-start artifact imported for session: ${TARGET_SESSION_ID}"
echo "Start inference with: TRIDENT_WORKER_MODE=inference ${SCRIPT_DIR}/start-analysis.sh"
