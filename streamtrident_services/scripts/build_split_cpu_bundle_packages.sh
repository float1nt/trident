#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
UI_DIR="${REPO_DIR}/V3-ui-2"
SOURCE_BUNDLE="${REPO_DIR}/streamtrident_cpu_bundle"
OUTPUT_DIR="${1:-${ROOT_DIR}/dist}"
WORK_DIR="${OUTPUT_DIR}/split_cpu_bundles_work"

CAPTURE_BUNDLE_NAME="${CAPTURE_BUNDLE_NAME:-streamtrident_cpu_capture_bundle}"
ANALYSIS_BUNDLE_NAME="${ANALYSIS_BUNDLE_NAME:-streamtrident_cpu_analysis_bundle}"
RELEASE_TS="${RELEASE_TS:-$(date +%Y%m%d%H%M%S)}"
CAPTURE_IMAGE_TAR="streamtrident-capture-cpu-images.tar"
ANALYSIS_IMAGE_TAR="streamtrident-analysis-cpu-images.tar"
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

capture_images=(
  redis:7-alpine
  "${REDIS_ADMIN_IMAGE}"
  "${SURICATA_CIC_IMAGE}"
  "${SURICATA_AGENT_IMAGE}"
  streamtrident/redis-admin:local
  streamtrident/suricata-cic:local
  streamtrident/suricata-agent:local
)

analysis_images=(
  "${TRIDENT_IMAGE}"
  clickhouse/clickhouse-server:24.8
  postgres:16-alpine
  "${UI_IMAGE}"
  streamtrident/trident:cpu-protected
  v3-ui-2:latest
)

require_file() {
  local path="$1"
  if [ ! -f "${path}" ]; then
    echo "Missing required file: ${path}" >&2
    exit 2
  fi
}

require_image() {
  local image="$1"
  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Missing required image: ${image}" >&2
    exit 1
  fi
}

ensure_or_pull_image() {
  local image="$1"
  if docker image inspect "${image}" >/dev/null 2>&1; then
    return 0
  fi
  docker pull "${image}"
}

write_capture_deploy_env() {
  local output="$1"
  cat > "${output}" <<'EOF'
# StreamTrident CPU 采集侧部署配置。
# 在采集机运行 scripts/start-capture.sh 前，请按真实环境修改本文件。

# 采集端主机 IP。分机部署时填写采集服务器真实 IP。
CAPTURE_HOST=127.0.0.1

# Suricata 抓包网卡名。必须改成采集端机器上的真实网卡，例如 eth0、ens35、enp3s0。
SURICATA_IFACE=eth0

# 采集端暴露给分析端的端口。
REDIS_HOST_PORT=16379
SURICATA_AGENT_HOST_PORT=19100

# 可选：采集规则管理接口共享 token。分析侧必须配置相同值。
TRIDENT_SURICATA_AGENT_TOKEN=
EOF
}

write_analysis_deploy_env() {
  local output="$1"
  cat > "${output}" <<'EOF'
# StreamTrident CPU 分析侧部署配置。
# 在分析机运行 scripts/start-analysis*.sh 或 scripts/start-ui.sh 前，请按真实环境修改本文件。

# 采集端主机 IP。分机部署时填写采集服务器真实 IP。
CAPTURE_HOST=127.0.0.1

# 采集端 Redis 和 Suricata agent 访问地址。
REDIS_HOST_PORT=16379
SURICATA_AGENT_HOST_PORT=19100
CAPTURE_REDIS_HOST=${CAPTURE_HOST}
CAPTURE_REDIS_PORT=${REDIS_HOST_PORT}
TRIDENT_SURICATA_AGENT_URLS=http://${CAPTURE_HOST}:${SURICATA_AGENT_HOST_PORT}

# 可选：采集规则管理接口共享 token。采集侧必须配置相同值。
TRIDENT_SURICATA_AGENT_TOKEN=

# 分析端 Trident API 端口。
TRIDENT_API_HOST_PORT=8090

# 前端 UI 访问端口。
UI_HOST_PORT=8088

# 前端 UI 容器名。
UI_CONTAINER_NAME=streamtrident-ui

# Worker 运行模式。首次建模先用 cold_start；冷启动完成后改成 inference。
TRIDENT_WORKER_MODE=cold_start

# 分析端主机 IP。UI 与分析端分机部署时填写分析服务器真实 IP。
ANALYSIS_HOST=127.0.0.1

# 前端反向代理后端地址。
API_AUTH_UPSTREAM=http://${ANALYSIS_HOST}:${TRIDENT_API_HOST_PORT}
API_TRIDENT_UPSTREAM=http://${ANALYSIS_HOST}:${TRIDENT_API_HOST_PORT}
EOF
}

patch_install_default_tar() {
  local install_script="$1"
  local image_tar="$2"
  sed -i "s#streamtrident-cpu-images.tar#${image_tar}#g" "${install_script}"
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

write_capture_stop_script() {
  local output="$1"
  cat > "${output}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

if [ -f "${RUNTIME_DIR}/capture/compose.yaml" ]; then
  docker compose -f "${RUNTIME_DIR}/capture/compose.yaml" down
fi
EOF
}

write_analysis_stop_script() {
  local output="$1"
  cat > "${output}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

for file in \
  "${RUNTIME_DIR}/ui/compose.yaml" \
  "${RUNTIME_DIR}/analysis/compose.yaml"; do
  if [ -f "${file}" ]; then
    docker compose -f "${file}" down
  fi
done
EOF
}

copy_scripts() {
  local target="$1"
  shift
  mkdir -p "${target}/scripts"
  for script in "$@"; do
    require_file "${SOURCE_BUNDLE}/scripts/${script}"
    cp "${SOURCE_BUNDLE}/scripts/${script}" "${target}/scripts/${script}"
  done
}

package_bundle() {
  local bundle_name="$1"
  local archive_path="${OUTPUT_DIR}/${bundle_name}-${RELEASE_TS}.tar.gz"
  tar -czf "${archive_path}" -C "${WORK_DIR}" "${bundle_name}"
  echo "Created package: ${archive_path}"
  du -h "${archive_path}" | awk '{print "Package size: " $1}'
}

require_file "${SOURCE_BUNDLE}/scripts/common.sh"
require_file "${SOURCE_BUNDLE}/scripts/install.sh"

mkdir -p "${OUTPUT_DIR}"
rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/images" "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/images"

echo "Using APT_MIRROR=${APT_MIRROR}"
echo "Using PIP_INDEX_URL=${PIP_INDEX_URL}"
echo "Using TORCH_VERSION=${TORCH_VERSION}"
echo "Using TORCH_INDEX_URL=${TORCH_INDEX_URL}"

echo "[1/6] Checking existing capture images"
require_image streamtrident/redis-admin:local
require_image streamtrident/suricata-cic:local
require_image streamtrident/suricata-agent:local

echo "[2/6] Ensuring third-party runtime images"
ensure_or_pull_image redis:7-alpine
ensure_or_pull_image clickhouse/clickhouse-server:24.8
ensure_or_pull_image postgres:16-alpine

echo "[3/6] Preparing protected CPU analysis and UI images"
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

echo "[4/6] Saving split image archives"
docker save "${capture_images[@]}" -o "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/images/${CAPTURE_IMAGE_TAR}"
docker save "${analysis_images[@]}" -o "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/images/${ANALYSIS_IMAGE_TAR}"
chmod 644 \
  "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/images/${CAPTURE_IMAGE_TAR}" \
  "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/images/${ANALYSIS_IMAGE_TAR}"

echo "[5/6] Assembling install bundle directories"
write_capture_deploy_env "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/deploy.env"
write_analysis_deploy_env "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/deploy.env"

copy_scripts "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}" \
  common.sh \
  install.sh \
  start-capture.sh \
  check-capture.sh \
  update-capture.sh
write_capture_stop_script "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/scripts/stop-capture.sh"
patch_install_default_tar "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/scripts/install.sh" "${CAPTURE_IMAGE_TAR}"
patch_common_image_tags "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/scripts/common.sh"

copy_scripts "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}" \
  common.sh \
  install.sh \
  start-analysis.sh \
  start-analysis-coldstart.sh \
  start-analysis-inference.sh \
  start-ui.sh \
  analysis-logs.sh \
  analysis-worker-log.sh \
  check-capture.sh \
  export-coldstart-artifact.sh \
  import-coldstart-artifact.sh \
  reset-analysis-data.sh \
  update-analysis.sh
write_analysis_stop_script "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/scripts/stop-analysis.sh"
patch_install_default_tar "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/scripts/install.sh" "${ANALYSIS_IMAGE_TAR}"
patch_common_image_tags "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/scripts/common.sh"

chmod +x "${WORK_DIR}/${CAPTURE_BUNDLE_NAME}/scripts/"*.sh
chmod +x "${WORK_DIR}/${ANALYSIS_BUNDLE_NAME}/scripts/"*.sh

echo "[6/6] Creating compressed install packages"
package_bundle "${CAPTURE_BUNDLE_NAME}"
package_bundle "${ANALYSIS_BUNDLE_NAME}"

echo "Done."
echo "Capture package: ${OUTPUT_DIR}/${CAPTURE_BUNDLE_NAME}-${RELEASE_TS}.tar.gz"
echo "Analysis package: ${OUTPUT_DIR}/${ANALYSIS_BUNDLE_NAME}-${RELEASE_TS}.tar.gz"
