#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAR="${1:-${BUNDLE_DIR}/images/streamtrident-cpu-images.tar}"

if [ ! -f "${IMAGE_TAR}" ]; then
  echo "Image tar not found: ${IMAGE_TAR}" >&2
  exit 2
fi

docker load -i "${IMAGE_TAR}"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -E '^(streamtrident/|v3-ui-2:|redis:7-alpine|postgres:16-alpine|clickhouse/clickhouse-server:24.8)'
