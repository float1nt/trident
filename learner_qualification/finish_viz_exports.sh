#!/usr/bin/env bash
# Compatibility wrapper: rebuild all visualization artifacts for an existing run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"  # project root
cd "$ROOT"

RUN_DIR="${1:-}"
if [[ -z "$RUN_DIR" ]]; then
  RUN_DIR="$(ls -1dt outputs/runs/*_config_fpr1_x5_yeartagged_viz.yaml 2>/dev/null | head -1)"
fi
if [[ -z "$RUN_DIR" || ! -d "$RUN_DIR" ]]; then
  echo "Usage: $0 [outputs/runs/<run_id>]" >&2
  exit 1
fi

if [[ ! -f "$RUN_DIR/run_summary.txt" ]]; then
  echo "Run not finished yet (no run_summary.txt): $RUN_DIR" >&2
  exit 2
fi

echo "Exporting for $RUN_DIR ..."
PYTHONPATH=. python3 learner_qualification/export_visualization_artifacts.py "$RUN_DIR"
echo "Done. visualize -> 学习器详情 -> $(basename "$RUN_DIR")"
