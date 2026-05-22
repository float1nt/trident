#!/usr/bin/env bash
# Export learner topology + metric audit after Trident run completes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
PYTHONPATH=. python3 scripts/export_learner_network_topology.py "$RUN_DIR"
PYTHONPATH=. python3 scripts/export_learner_topology_metric_audit.py "$RUN_DIR"
echo "Done. visualize -> 学习器详情 -> $(basename "$RUN_DIR")"
