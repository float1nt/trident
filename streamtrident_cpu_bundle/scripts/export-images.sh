#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${1:-${BUNDLE_DIR}/images/streamtrident-cpu-images.tar}"

mkdir -p "$(dirname "${OUTPUT}")"

required_images=(
  streamtrident/trident:cpu-protected
  streamtrident/redis-admin:local
  streamtrident/suricata-cic:local
  streamtrident/suricata-agent:local
  v3-ui-2:latest
  redis:7-alpine
  clickhouse/clickhouse-server:24.8
  postgres:16-alpine
)

for image in "${required_images[@]}"; do
  docker image inspect "${image}" >/dev/null
done

docker save "${required_images[@]}" -o "${OUTPUT}"
chmod 644 "${OUTPUT}"
ls -lh "${OUTPUT}"
