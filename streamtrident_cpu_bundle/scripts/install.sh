#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAR="${1:-${BUNDLE_DIR}/images/streamtrident-cpu-images.tar}"

if [ ! -f "${IMAGE_TAR}" ]; then
  echo "Image tar not found: ${IMAGE_TAR}" >&2
  exit 2
fi

echo "导入镜像包: ${IMAGE_TAR}"
echo "镜像包大小: $(du -h "${IMAGE_TAR}" | awk '{print $1}')"

if command -v pv >/dev/null 2>&1; then
  pv "${IMAGE_TAR}" | docker load
else
  echo "未检测到 pv，使用 dd 显示读取进度。"
  echo "如需更清晰进度条，可安装 pv: apt-get install -y pv"
  dd if="${IMAGE_TAR}" bs=16M status=progress | docker load
fi

echo
echo "已导入镜像:"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -E '^(streamtrident/|v3-ui-2:|redis:7-alpine|postgres:16-alpine|clickhouse/clickhouse-server:24.8)'
