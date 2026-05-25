#!/usr/bin/env bash
# Static CSV → Suricata Redis Stream format → Trident benchmark (full performance metrics).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MAX_ROWS="${MAX_ROWS:-10000}"
CONFIG="${CONFIG:-configs/benchmark_redis_live.yaml}"
COMPOSE_DIR="$ROOT/suricata-cic-redis-live"

echo "==> [1/5] Start Redis (docker compose)"
docker compose -f "$COMPOSE_DIR/docker-compose.yml" up -d redis

echo "==> [2/5] Install Python redis if needed"
python3 -m pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org redis 2>/dev/null \
  || pip3 install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org redis

echo "==> [3/5] Inject static CSV into suricata:cic_flow ($MAX_ROWS rows)"
python3 scripts/inject_csv_to_suricata_redis.py \
  --max-rows "$MAX_ROWS" \
  --clear-stream \
  --url redis://127.0.0.1:6379/0

echo "==> [4/5] Run Trident performance benchmark (Redis input)"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/mplconfig-trident}"
python3 scripts/benchmark_trident_performance.py \
  --config "$CONFIG" \
  --max-rows "$MAX_ROWS"

RUN_DIR="$(ls -td outputs/runs/*benchmark_redis_live.yaml 2>/dev/null | head -1)"
echo "==> [5/5] Done"
echo "Run output: $RUN_DIR"
if [[ -f "$RUN_DIR/trident_performance_benchmark.json" ]]; then
  echo "--- trident_performance_benchmark.json ---"
  cat "$RUN_DIR/trident_performance_benchmark.json"
fi
