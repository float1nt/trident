#!/usr/bin/env bash
# Deprecated: use learner_qualification/finish_viz_exports.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Note: scripts/finish_viz_exports.sh -> learner_qualification/finish_viz_exports.sh" >&2
exec bash "$ROOT/learner_qualification/finish_viz_exports.sh" "$@"
