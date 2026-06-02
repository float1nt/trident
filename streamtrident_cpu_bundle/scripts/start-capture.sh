#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

prepare_runtime
docker compose -f "${RUNTIME_DIR}/capture/compose.yaml" up -d
echo "Capture started. Set SURICATA_IFACE to the real NIC before production use."
