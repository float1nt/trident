#!/usr/bin/env bash
# Deprecated: use learner_qualification/run_aligned_viz_pipeline.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Note: scripts/run_aligned_viz_pipeline.sh -> learner_qualification/run_aligned_viz_pipeline.sh" >&2
exec bash "$ROOT/learner_qualification/run_aligned_viz_pipeline.sh" "$@"
