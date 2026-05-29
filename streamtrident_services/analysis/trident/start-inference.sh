#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python -m app.worker --config "${TRIDENT_CONFIG:-config/trident.yaml}" --mode inference

