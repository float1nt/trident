#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

load_deploy_env
prepare_runtime

tail -f "${RUNTIME_DIR}/analysis/trident/logs/worker.log"
