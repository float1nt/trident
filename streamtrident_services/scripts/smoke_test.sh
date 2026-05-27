#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/compose.yaml}"
PROJECT_DIR="$(dirname "$COMPOSE_FILE")"
RUN_ID="${RUN_ID:-smoke-$(date +%Y%m%d%H%M%S)}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-180}"
FLOW_COUNT="${FLOW_COUNT:-25}"
API_URL="${API_URL:-http://127.0.0.1:8090}"

cd "$PROJECT_DIR"

log() {
  printf '[smoke] %s\n' "$*"
}

fail() {
  printf '[smoke][FAIL] %s\n' "$*" >&2
  exit 1
}

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

wait_for_container_running() {
  local service="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    local status
    status="$(compose ps --status running --services 2>/dev/null | awk -v s="$service" '$0 == s {print $0}' || true)"
    if [[ "$status" == "$service" ]]; then
      return 0
    fi
    sleep 2
  done
  fail "service did not reach running state: $service"
}

wait_for_one_shot_success() {
  local service="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    local id status
    id="$(compose ps -a -q "$service" 2>/dev/null || true)"
    if [[ -n "$id" ]]; then
      status="$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$id" 2>/dev/null || true)"
      if [[ "$status" == "exited 0" ]]; then
        return 0
      fi
      if [[ "$status" =~ ^exited\  && "$status" != "exited 0" ]]; then
        compose logs --tail=80 "$service" >&2 || true
        fail "one-shot service failed: $service ($status)"
      fi
    fi
    sleep 2
  done
  fail "one-shot service did not finish successfully: $service"
}

redis_cmd() {
  compose exec -T redis redis-cli "$@"
}

clickhouse_query() {
  compose exec -T clickhouse clickhouse-client --query "$1"
}

postgres_query() {
  compose exec -T postgres psql -U trident -d trident -Atc "$1"
}

api_get() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$API_URL$1"
  else
    python3 - "$API_URL$1" <<'PY'
import sys
from urllib.request import urlopen
print(urlopen(sys.argv[1], timeout=5).read().decode("utf-8"))
PY
  fi
}

wait_for_api_health() {
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if api_get "/api/v1/health" >/tmp/streamtrident_smoke_health.json 2>/dev/null; then
      if grep -q '"code":0' /tmp/streamtrident_smoke_health.json; then
        return 0
      fi
      cat /tmp/streamtrident_smoke_health.json >&2
    fi
    sleep 2
  done
  fail "API health did not become ready"
}

log "compose file: $COMPOSE_FILE"
log "run id: $RUN_ID"

if [ "${SMOKE_BUILD:-0}" = "1" ]; then
  log "building local images"
  compose build trident-migrate trident-worker trident-api redis-admin
fi

log "starting core services"
compose rm -fs redis-admin trident-migrate >/dev/null 2>&1 || true
compose up -d redis clickhouse postgres redis-admin trident-migrate trident-worker trident-api

wait_for_container_running redis
wait_for_container_running clickhouse
wait_for_container_running postgres
wait_for_one_shot_success redis-admin
wait_for_one_shot_success trident-migrate
wait_for_container_running trident-worker
wait_for_container_running trident-api

log "checking API health"
wait_for_api_health

log "injecting $FLOW_COUNT flow records"
for i in $(seq 1 "$FLOW_COUNT"); do
  event_time="2026-05-26T12:00:$(printf '%02d' "$((i % 60))")Z"
  source_flow_id="${RUN_ID}-${i}"
  src_ip="10.10.0.$((i % 250 + 1))"
  dst_ip="172.16.0.$((i % 20 + 1))"
  src_port="$((20000 + i))"
  dst_port="$((443 + (i % 3)))"
  features_json="{\"Flow Duration\":$((1000 + i)),\"Total Fwd Packet\":$((2 + i % 5)),\"Total Bwd packets\":$((1 + i % 4)),\"Total Length of Fwd Packet\":$((500 + i)),\"Total Length of Bwd Packet\":$((400 + i)),\"Fwd Packet Length Mean\":64,\"Fwd Packet Length Std\":1,\"Bwd Packet Length Min\":40,\"Bwd Packet Length Max\":80,\"Bwd Packet Length Mean\":60,\"Bwd Packet Length Std\":2,\"Flow Bytes/s\":$((10000 + i)),\"Flow Packets/s\":10,\"Flow IAT Mean\":5,\"Flow IAT Std\":1,\"Fwd IAT Mean\":5,\"Fwd IAT Std\":1,\"Bwd IAT Mean\":5,\"Bwd IAT Std\":1,\"Packet Length Mean\":60,\"Packet Length Std\":3,\"SYN Flag Count\":1,\"ACK Flag Count\":1,\"PSH Flag Count\":0,\"Average Packet Size\":70,\"FWD Init Win Bytes\":1024,\"Bwd Header Length\":20,\"Fwd Bulk Rate Avg\":0,\"Bwd Bulk Rate Avg\":0,\"Active Mean\":1,\"Active Std\":0,\"Active Max\":1,\"Idle Mean\":1,\"Idle Std\":0}"
  redis_cmd XADD suricata:cic_flow '*' \
    event_type cic_flow \
    event_time "$event_time" \
    session_id suricata-live \
    src_ip "$src_ip" \
    dst_ip "$dst_ip" \
    src_port "$src_port" \
    dst_port "$dst_port" \
    protocol TCP \
    source_flow_id "$source_flow_id" \
    features_json "$features_json" \
    raw_event_json "{\"source_flow_id\":\"$source_flow_id\",\"smoke_run_id\":\"$RUN_ID\"}" >/dev/null
done

log "waiting for ClickHouse ingested/assigned rows"
deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  ingested="$(clickhouse_query "SELECT count() FROM ch_flow FINAL WHERE source_flow_id LIKE '${RUN_ID}-%' AND record_stage = 'ingested'")"
  assigned="$(clickhouse_query "SELECT count() FROM ch_flow FINAL WHERE source_flow_id LIKE '${RUN_ID}-%' AND record_stage = 'assigned'")"
  if (( ingested + assigned >= FLOW_COUNT )) && (( assigned > 0 )); then
    log "ClickHouse rows visible: ingested=$ingested assigned=$assigned"
    break
  fi
  sleep 3
done
if (( SECONDS >= deadline )); then
  compose logs --tail=120 trident-worker >&2 || true
  fail "timed out waiting for ClickHouse rows"
fi

log "checking PostgreSQL learner state"
learner_count="$(postgres_query "SELECT count(*) FROM pg_learner WHERE session_id = 'trident-session-dev';")"
snapshot_count="$(postgres_query "SELECT count(*) FROM pg_learner_snapshot WHERE session_id = 'trident-session-dev';")"
if (( learner_count < 1 )); then
  fail "no pg_learner rows found"
fi
if (( snapshot_count < 1 )); then
  fail "no pg_learner_snapshot rows found"
fi
log "PostgreSQL rows visible: learners=$learner_count snapshots=$snapshot_count"

log "checking Redis output streams"
assign_len="$(redis_cmd XLEN trident:assignments)"
metrics_len="$(redis_cmd XLEN trident:metrics)"
if (( assign_len < 1 )); then
  fail "trident:assignments is empty"
fi
if (( metrics_len < 1 )); then
  fail "trident:metrics is empty"
fi
log "Redis output streams: assignments=$assign_len metrics=$metrics_len"

log "checking API /flows"
api_get "/api/v1/flows?limit=5" >/tmp/streamtrident_smoke_flows.json || fail "API /flows failed"
if ! grep -q '"items"' /tmp/streamtrident_smoke_flows.json; then
  cat /tmp/streamtrident_smoke_flows.json >&2
  fail "API /flows did not return items"
fi

log "smoke test passed"
