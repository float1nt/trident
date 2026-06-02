#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
UI_DIR="${REPO_DIR}/V3-ui-2"
OUTPUT="${1:-${ROOT_DIR}/dist/streamtrident-cpu-images.tar}"

export APT_MIRROR="${APT_MIRROR:-mirrors.aliyun.com}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export TORCH_VERSION="${TORCH_VERSION:-2.7.0+cpu}"
export TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
BUILD_ANALYSIS="${BUILD_ANALYSIS:-1}"
BUILD_UI="${BUILD_UI:-1}"

mkdir -p "$(dirname "${OUTPUT}")"

echo "Using APT_MIRROR=${APT_MIRROR}"
echo "Using PIP_INDEX_URL=${PIP_INDEX_URL}"
echo "Using TORCH_VERSION=${TORCH_VERSION}"
echo "Using TORCH_INDEX_URL=${TORCH_INDEX_URL}"

require_image() {
  local image="$1"
  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Missing required image: ${image}" >&2
    return 1
  fi
}

ensure_or_pull_image() {
  local image="$1"
  if docker image inspect "${image}" >/dev/null 2>&1; then
    return 0
  fi
  docker pull "${image}"
}

echo "[1/4] Checking existing capture images"
require_image streamtrident/redis-admin:local
require_image streamtrident/suricata-cic:local
require_image streamtrident/suricata-agent:local

echo "[2/4] Ensuring third-party runtime images"
ensure_or_pull_image redis:7-alpine
ensure_or_pull_image clickhouse/clickhouse-server:24.8
ensure_or_pull_image postgres:16-alpine

echo "[3/4] Preparing protected CPU analysis and UI images"
if [ "${BUILD_ANALYSIS}" = "1" ]; then
  docker compose \
    -f "${ROOT_DIR}/analysis/compose.yaml" \
    -f "${ROOT_DIR}/analysis/compose.protected-cpu.yaml" \
    -f "${ROOT_DIR}/analysis/compose.cpu.yaml" \
    build trident-migrate trident-worker trident-api
else
  require_image streamtrident/trident:cpu-protected
fi

if [ "${BUILD_UI}" = "1" ]; then
  docker compose -f "${UI_DIR}/compose.yaml" build
else
  require_image v3-ui-2:latest
fi

echo "[4/4] Saving image package: ${OUTPUT}"
docker save \
  streamtrident/trident:cpu-protected \
  streamtrident/redis-admin:local \
  streamtrident/suricata-cic:local \
  streamtrident/suricata-agent:local \
  v3-ui-2:latest \
  redis:7-alpine \
  clickhouse/clickhouse-server:24.8 \
  postgres:16-alpine \
  -o "${OUTPUT}"

echo "Done: ${OUTPUT}"
