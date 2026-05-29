#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../trident"
python -m app.worker --config "${TRIDENT_CONFIG:-config/trident.yaml}" --mode cold_start
