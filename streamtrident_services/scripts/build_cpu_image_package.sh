#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
UI_DIR="${REPO_DIR}/V3-ui-2"
OUTPUT="${1:-${ROOT_DIR}/dist/streamtrident-cpu-images.tar}"
BUNDLE_SOURCE_DIR="${REPO_DIR}/streamtrident_cpu_bundle"
BUNDLE_NAME="${BUNDLE_NAME:-streamtrident_cpu_bundle}"
RELEASE_TS="${RELEASE_TS:-$(date +%Y%m%d%H%M%S)}"
BUNDLE_OUTPUT="${BUNDLE_OUTPUT:-$(dirname "${OUTPUT}")/${BUNDLE_NAME}-${RELEASE_TS}.tar.gz}"
BUNDLE_WORK_DIR="${BUNDLE_WORK_DIR:-$(dirname "${OUTPUT}")}/${BUNDLE_NAME}_work"
TRIDENT_IMAGE="streamtrident/trident:cpu-protected-${RELEASE_TS}"
REDIS_ADMIN_IMAGE="streamtrident/redis-admin:local-${RELEASE_TS}"
SURICATA_CIC_IMAGE="streamtrident/suricata-cic:local-${RELEASE_TS}"
SURICATA_AGENT_IMAGE="streamtrident/suricata-agent:local-${RELEASE_TS}"
UI_IMAGE="v3-ui-2:${RELEASE_TS}"

export APT_MIRROR="${APT_MIRROR:-mirrors.aliyun.com}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export TORCH_VERSION="${TORCH_VERSION:-2.7.0+cpu}"
export TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
BUILD_ANALYSIS="${BUILD_ANALYSIS:-1}"
BUILD_UI="${BUILD_UI:-1}"
BUILD_BUNDLE="${BUILD_BUNDLE:-1}"

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

require_file() {
  local path="$1"
  if [ ! -f "${path}" ]; then
    echo "Missing required file: ${path}" >&2
    exit 2
  fi
}

tag_release_images() {
  docker tag streamtrident/trident:cpu-protected "${TRIDENT_IMAGE}"
  docker tag streamtrident/redis-admin:local "${REDIS_ADMIN_IMAGE}"
  docker tag streamtrident/suricata-cic:local "${SURICATA_CIC_IMAGE}"
  docker tag streamtrident/suricata-agent:local "${SURICATA_AGENT_IMAGE}"
  docker tag v3-ui-2:latest "${UI_IMAGE}"
}

patch_common_image_tags() {
  local common_script="$1"
  sed -i \
    -e "s#streamtrident/trident:cpu-protected#${TRIDENT_IMAGE}#g" \
    -e "s#streamtrident/redis-admin:local#${REDIS_ADMIN_IMAGE}#g" \
    -e "s#streamtrident/suricata-cic:local#${SURICATA_CIC_IMAGE}#g" \
    -e "s#streamtrident/suricata-agent:local#${SURICATA_AGENT_IMAGE}#g" \
    -e "s#v3-ui-2:latest#${UI_IMAGE}#g" \
    "${common_script}"
}

build_bundle_archive() {
  local image_tar="$1"

  require_file "${BUNDLE_SOURCE_DIR}/deploy.env"
  require_file "${BUNDLE_SOURCE_DIR}/scripts/install.sh"
  require_file "${BUNDLE_SOURCE_DIR}/scripts/common.sh"

  echo "Creating install bundle: ${BUNDLE_OUTPUT}"
  rm -rf "${BUNDLE_WORK_DIR}"
  mkdir -p "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/images"

  cp "${BUNDLE_SOURCE_DIR}/deploy.env" "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/deploy.env"
  cp -a "${BUNDLE_SOURCE_DIR}/scripts" "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/scripts"
  patch_common_image_tags "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/scripts/common.sh"
  cp "${image_tar}" "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/images/streamtrident-cpu-images.tar"
  chmod 644 "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/images/streamtrident-cpu-images.tar"
  chmod +x "${BUNDLE_WORK_DIR}/${BUNDLE_NAME}/scripts/"*.sh

  tar -czf "${BUNDLE_OUTPUT}" -C "${BUNDLE_WORK_DIR}" "${BUNDLE_NAME}"
  echo "Done bundle: ${BUNDLE_OUTPUT}"
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

echo "Tagging release images with RELEASE_TS=${RELEASE_TS}"
tag_release_images

echo "[4/4] Saving image package: ${OUTPUT}"
docker save \
  "${TRIDENT_IMAGE}" \
  "${REDIS_ADMIN_IMAGE}" \
  "${SURICATA_CIC_IMAGE}" \
  "${SURICATA_AGENT_IMAGE}" \
  "${UI_IMAGE}" \
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

if [ "${BUILD_BUNDLE}" = "1" ]; then
  build_bundle_archive "${OUTPUT}"
fi
