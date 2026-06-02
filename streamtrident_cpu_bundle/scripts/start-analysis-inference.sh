#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TRIDENT_WORKER_MODE=inference
exec "${SCRIPT_DIR}/start-analysis.sh"
