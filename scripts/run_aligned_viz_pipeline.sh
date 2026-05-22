#!/usr/bin/env bash
# Build aligned x5 yeartagged CSV from data/{cic2017,cicids2019,cicids2026.csv},
# run Trident, then export learner topology + metric audit for visualize.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ALIGNED_CSV="data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv"
REPORT_JSON="data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.report.json"
TRIDENT_CFG="configs/experiments/viz_pipeline/config_fpr1_x5_yeartagged_viz.yaml"

echo "[1/4] prepare_threeway_sampled_dataset (x5 benign) ..."
python3 scripts/prepare_threeway_sampled_dataset.py \
  --dir-2017 data/cic2017 \
  --dir-2019 data/cicids2019 \
  --file-2026 data/cicids2026.csv \
  --benign-multiplier 5 \
  --benign-per-year 100000 \
  --attack-per-type 10000 \
  --output-csv "$ALIGNED_CSV" \
  --report-json "$REPORT_JSON"

echo "[2/4] Trident streaming run ..."
python3 main.py --config "$TRIDENT_CFG"

RUN_DIR="$(ls -1dt outputs/runs/*_config_fpr1_x5_yeartagged_viz.yaml 2>/dev/null | head -1)"
if [[ -z "${RUN_DIR:-}" ]]; then
  echo "ERROR: no run dir found for config_fpr1_x5_yeartagged_viz.yaml" >&2
  exit 1
fi
echo "Run directory: $RUN_DIR"

echo "[3/4] export learner_network_topology.json ..."
PYTHONPATH=. python3 scripts/export_learner_network_topology.py "$RUN_DIR"

echo "[4/4] export learner_topology_metric_audit.json ..."
PYTHONPATH=. python3 scripts/export_learner_topology_metric_audit.py "$RUN_DIR"

echo "DONE. Open visualize -> 学习器详情 with run: $(basename "$RUN_DIR")"
