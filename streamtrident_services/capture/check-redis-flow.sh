#!/usr/bin/env bash
# Verify capture-side Redis is reachable and flow records are arriving.
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE="${ENV_FILE:-.env}"
WATCH_SECONDS="${WATCH_SECONDS:-20}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-2}"
MIN_GROWTH="${MIN_GROWTH:-1}"
MIN_PEAK_LEN="${MIN_PEAK_LEN:-1}"

log() { printf '[check-redis] %s\n' "$*"; }
fail() { printf '[check-redis][FAIL] %s\n' "$*" >&2; exit 1; }
pass() { printf '[check-redis][OK] %s\n' "$*"; }

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  log "env file not found ($ENV_FILE), using defaults"
fi

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_HOST_PORT:-16379}"
STREAM_KEY="${SURICATA_REDIS_STREAM:-suricata:cic_flow}"
QUEUE_MODE="${SURICATA_REDIS_OUTPUT_MODE:-list}"
USE_DOCKER="${USE_DOCKER:-auto}"

redis_cli() {
  if [ "$USE_DOCKER" = "1" ] || { [ "$USE_DOCKER" = "auto" ] && docker compose ps -q redis 2>/dev/null | grep -q .; }; then
    docker compose exec -T redis redis-cli "$@"
  else
    command -v redis-cli >/dev/null 2>&1 || fail "redis-cli not found; install redis-tools or set USE_DOCKER=1"
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "$@"
  fi
}

redis_ping() {
  redis_cli PING 2>/dev/null | tr -d '\r'
}

queue_len() {
  local key_type len
  key_type="$(redis_cli TYPE "$STREAM_KEY" 2>/dev/null | tr -d '\r')"
  case "$key_type" in
    list)
      len="$(redis_cli LLEN "$STREAM_KEY" 2>/dev/null | tr -d '\r')"
      ;;
    stream)
      len="$(redis_cli XLEN "$STREAM_KEY" 2>/dev/null | tr -d '\r')"
      ;;
    none)
      echo 0
      return 0
      ;;
    *)
      fail "unexpected Redis key type for $STREAM_KEY: $key_type (expected list or stream)"
      ;;
  esac
  echo "${len:-0}"
}

fetch_sample() {
  local key_type
  key_type="$(redis_cli TYPE "$STREAM_KEY" 2>/dev/null | tr -d '\r')"
  case "$key_type" in
    list)
      redis_cli LRANGE "$STREAM_KEY" -1 -1 2>/dev/null | head -n 1
      ;;
    stream)
      redis_cli XREVRANGE "$STREAM_KEY" + - COUNT 1 2>/dev/null | awk 'NR==2 {print; exit}'
      ;;
    *)
      echo ""
      ;;
  esac
}

log "redis=${REDIS_HOST}:${REDIS_PORT} key=${STREAM_KEY} mode=${QUEUE_MODE} watch=${WATCH_SECONDS}s"

ping_reply="$(redis_ping || true)"
if [ "$ping_reply" != "PONG" ]; then
  fail "Redis not reachable (${REDIS_HOST}:${REDIS_PORT}, got: ${ping_reply:-<empty>})"
fi
pass "Redis PING ok"

actual_type="$(redis_cli TYPE "$STREAM_KEY" 2>/dev/null | tr -d '\r')"
if [ "$actual_type" = "none" ]; then
  log "key $STREAM_KEY does not exist yet; waiting for first records..."
elif [ "$QUEUE_MODE" = "list" ] && [ "$actual_type" != "list" ]; then
  fail "SURICATA_REDIS_OUTPUT_MODE=list but key type is $actual_type"
elif [ "$QUEUE_MODE" = "stream" ] && [ "$actual_type" != "stream" ]; then
  fail "SURICATA_REDIS_OUTPUT_MODE=stream but key type is $actual_type"
fi

start_len="$(queue_len)"
max_len="$start_len"
end_len="$start_len"
samples=0

log "sampling queue length for ${WATCH_SECONDS}s (interval ${SAMPLE_INTERVAL}s)..."
watch_start=$SECONDS
deadline=$((watch_start + WATCH_SECONDS))
while (( SECONDS < deadline )); do
  len="$(queue_len)"
  samples=$((samples + 1))
  if (( len > max_len )); then
    max_len=$len
  fi
  end_len=$len
  log "  elapsed=$((SECONDS - watch_start))s llen=${len}"
  sleep "$SAMPLE_INTERVAL"
done

growth=$((max_len - start_len))
if (( max_len >= MIN_PEAK_LEN )); then
  pass "queue had data (peak=${max_len}, start=${start_len}, end=${end_len})"
elif (( growth >= MIN_GROWTH )); then
  pass "queue grew by ${growth} (start=${start_len}, peak=${max_len})"
else
  fail "no flow data observed on ${STREAM_KEY} in ${WATCH_SECONDS}s (start=${start_len}, peak=${max_len}, end=${end_len}); check mirror on ${SURICATA_IFACE:-<iface>} and suricata logs: docker logs streamtrident-suricata-cic"
fi

if [ "$end_len" -eq 0 ] && [ "$max_len" -gt 0 ]; then
  log "note: queue is empty now but peaked at ${max_len} — analysis worker may be consuming (pop) quickly"
fi

raw_sample="$(fetch_sample | tr -d '\r')"
if [ -z "$raw_sample" ]; then
  fail "could not fetch a sample record from ${STREAM_KEY}"
fi

python3 - "$raw_sample" <<'PY' || fail "sample record is not valid flow JSON"
import json
import sys

raw = sys.argv[1].strip()
try:
    payload = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid JSON: {exc}") from exc

if not isinstance(payload, dict):
    raise SystemExit(f"expected JSON object, got {type(payload).__name__}")

aliases = {
    "src_ip": ("src_ip", "source_ip", "Source IP", "Src IP"),
    "dst_ip": ("dst_ip", "dest_ip", "destination_ip", "Destination IP", "Dst IP"),
    "event_time": ("event_time", "timestamp", "Timestamp", "time", "flow_start"),
}

def pick(key: str):
    for name in aliases[key]:
        value = payload.get(name)
        if value not in (None, ""):
            return value
    return None

src_ip = pick("src_ip")
dst_ip = pick("dst_ip")
event_time = pick("event_time")
features = payload.get("features")
if features is None and isinstance(payload.get("features_json"), str):
    try:
        features = json.loads(payload["features_json"])
    except json.JSONDecodeError:
        features = None
if features is None and isinstance(payload.get("cic"), dict):
    features = payload["cic"]

missing = [name for name, value in (("src_ip", src_ip), ("dst_ip", dst_ip)) if not value]
if missing:
    raise SystemExit(f"missing fields in sample: {', '.join(missing)}")

print(
    "sample ok:",
    f"src={src_ip}",
    f"dst={dst_ip}",
    f"time={event_time or '<missing>'}",
    f"feature_keys={len(features) if isinstance(features, dict) else 0}",
    f"json_bytes={len(raw)}",
)
PY

pass "capture Redis flow ingest looks healthy"
