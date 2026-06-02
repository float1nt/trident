#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

load_deploy_env
prepare_runtime

docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" logs -f --tail=200 trident-worker trident-api trident-migrate
