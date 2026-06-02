#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
UI_DIR="${REPO_DIR}/V3-ui-2"

export APT_MIRROR="${APT_MIRROR:-mirrors.aliyun.com}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export TORCH_VERSION="${TORCH_VERSION:-2.7.0+cpu}"
export TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"

BUILD_ANALYSIS="${BUILD_ANALYSIS:-1}"
BUILD_UI="${BUILD_UI:-1}"
BUILD_CAPTURE="${BUILD_CAPTURE:-0}"

echo "Using APT_MIRROR=${APT_MIRROR}"
echo "Using PIP_INDEX_URL=${PIP_INDEX_URL}"
echo "Using TORCH_VERSION=${TORCH_VERSION}"
echo "Using TORCH_INDEX_URL=${TORCH_INDEX_URL}"

if [ "${BUILD_CAPTURE}" = "1" ]; then
  echo "[1/3] Building capture images"
  docker compose -f "${ROOT_DIR}/capture/compose.yaml" build
else
  echo "[1/3] Skipping capture image build; existing capture images will be reused"
fi

if [ "${BUILD_ANALYSIS}" = "1" ]; then
  echo "[2/3] Building protected CPU analysis image"
  docker compose \
    -f "${ROOT_DIR}/analysis/compose.yaml" \
    -f "${ROOT_DIR}/analysis/compose.protected-cpu.yaml" \
    -f "${ROOT_DIR}/analysis/compose.cpu.yaml" \
    build trident-migrate trident-worker trident-api
else
  echo "[2/3] Skipping analysis image build"
fi

if [ "${BUILD_UI}" = "1" ]; then
  echo "[3/3] Building UI image"
  docker compose -f "${UI_DIR}/compose.yaml" build
else
  echo "[3/3] Skipping UI image build"
fi

docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep -E '^(streamtrident/trident:cpu-protected|v3-ui-2:latest|streamtrident/redis-admin:local|streamtrident/suricata-cic:local|streamtrident/suricata-agent:local)'
