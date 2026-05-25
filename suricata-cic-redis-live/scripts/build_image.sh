#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-suricata-cic-live:local}"

if [ ! -x "$ROOT_DIR/runtime/bin/suricata" ]; then
  echo "runtime binary not found: $ROOT_DIR/runtime/bin/suricata" >&2
  echo "run scripts/sync_runtime.sh first" >&2
  exit 1
fi

docker build \
  -t "$IMAGE" \
  -f "$ROOT_DIR/docker/Dockerfile" \
  "$ROOT_DIR"
