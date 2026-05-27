#!/usr/bin/env bash
set -euo pipefail

IFACE="${IFACE:-eth0}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-16379}"
REDIS_STREAM="${REDIS_STREAM:-suricata:cic_flow}"
REDIS_STREAM_MAXLEN="${REDIS_STREAM_MAXLEN:-1000000}"
CIC_MODE="${CIC_MODE:-cic-flowmeter}"
CIC_FLOW_TIMEOUT_US="${CIC_FLOW_TIMEOUT_US:-120000000}"
CIC_ACTIVE_IDLE_THRESHOLD_US="${CIC_ACTIVE_IDLE_THRESHOLD_US:-5000000}"
SURICATA_RUNMODE="${SURICATA_RUNMODE:-workers}"
SURICATA_EXTRA_ARGS="${SURICATA_EXTRA_ARGS:-}"
SURICATA_FILTER_CONFIG="${SURICATA_FILTER_CONFIG:-}"

BASE_CONF="/etc/suricata/suricata.yaml"
LIVE_CONF="/run/suricata-cic-live.yaml"
LOG_DIR="/var/log/suricata"

mkdir -p "$LOG_DIR" /run

if [ ! -r "$BASE_CONF" ]; then
  echo "missing Suricata config: $BASE_CONF" >&2
  exit 1
fi

if ! ip link show "$IFACE" >/dev/null 2>&1; then
  echo "network interface not found: $IFACE" >&2
  echo "available interfaces:" >&2
  ip -o link show | awk -F': ' '{print "  " $2}' >&2
  exit 1
fi

python3 - "$BASE_CONF" "$LIVE_CONF" "$REDIS_HOST" "$REDIS_PORT" "$REDIS_STREAM" \
  "$REDIS_STREAM_MAXLEN" "$CIC_MODE" "$CIC_FLOW_TIMEOUT_US" \
  "$CIC_ACTIVE_IDLE_THRESHOLD_US" "$SURICATA_FILTER_CONFIG" <<'PY'
import json
import sys
from pathlib import Path

base, out, redis_host, redis_port, redis_stream, redis_maxlen, cic_mode, flow_timeout, active_idle, filter_path = sys.argv[1:]

def load_filter(path: str) -> dict:
    if not path:
        return {}
    target = Path(path)
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid Suricata filter config: {path}")
    return payload

def range_values(payload: dict, key: str) -> list[str]:
    values = []
    for item in payload.get(key, []) or []:
        if not isinstance(item, dict):
            continue
        start = item.get("startIp")
        end = item.get("endIp")
        if start and end:
            values.append(f"{start}-{end}")
    return values

def scalar_values(payload: dict, key: str) -> list[str]:
    return [str(item).strip().lower() for item in (payload.get(key, []) or []) if str(item).strip()]

def append_filter(result: list[str], payload: dict) -> None:
    src_ranges = range_values(payload, "sourceIpRanges")
    dst_ranges = range_values(payload, "destIpRanges")
    protocols = scalar_values(payload, "protocols")
    if not src_ranges and not dst_ranges and not protocols:
        return
    result.append("            filter:")
    if src_ranges:
        result.append("              source-ip-ranges:")
        for value in src_ranges:
            result.append(f"                - {json.dumps(value)}")
    if dst_ranges:
        result.append("              dest-ip-ranges:")
        for value in dst_ranges:
            result.append(f"                - {json.dumps(value)}")
    if protocols:
        result.append("              protocols:")
        for value in protocols:
            result.append(f"                - {json.dumps(value)}")

filter_payload = load_filter(filter_path)
lines = Path(base).read_text(encoding="utf-8", errors="replace").splitlines()
result = []
skip = False
for line in lines:
    if line == "outputs:" and not skip:
        result.extend([
            "outputs:",
            "  - eve-log:",
            "      enabled: yes",
            "      filetype: redis",
            "      redis:",
            f"        server: {redis_host}",
            f"        port: {redis_port}",
            "        async: false",
            "        mode: stream",
            f"        key: {redis_stream}",
            f"        stream-maxlen: {redis_maxlen}",
            "      types:",
            "        - cic-flow:",
            "            enabled: yes",
            f"            mode: {cic_mode}",
            f"            flow-timeout-us: {flow_timeout}",
            f"            active-idle-threshold-us: {active_idle}",
        ])
        append_filter(result, filter_payload)
        result.extend([
            "  - stats:",
            "      enabled: yes",
            "      filename: stats.log",
            "      append: yes",
            "      totals: yes",
            "      threads: no",
        ])
        skip = True
        continue
    if skip and line.startswith("# Logging configuration."):
        skip = False
    if not skip:
        result.append(line)
Path(out).write_text("\n".join(result) + "\n", encoding="utf-8")
PY

echo "suricata-cic starting"
echo "  iface=$IFACE"
echo "  redis=$REDIS_HOST:$REDIS_PORT"
echo "  stream=$REDIS_STREAM"
echo "  mode=$CIC_MODE"
echo "  log_dir=$LOG_DIR"
if [ -n "$SURICATA_FILTER_CONFIG" ] && [ -r "$SURICATA_FILTER_CONFIG" ]; then
  echo "  filter_config=$SURICATA_FILTER_CONFIG"
else
  echo "  filter_config=<none>"
fi

redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" PING >/dev/null

/opt/suricata-cic/bin/suricata -T -c "$LIVE_CONF" -l "$LOG_DIR" \
  -S /var/lib/suricata/rules/empty.rules \
  --set classification-file=/etc/suricata/classification.config \
  --set reference-config-file=/etc/suricata/reference.config

exec /opt/suricata-cic/bin/suricata \
  --runmode="$SURICATA_RUNMODE" \
  -i "$IFACE" \
  -c "$LIVE_CONF" \
  -l "$LOG_DIR" \
  -k none \
  -S /var/lib/suricata/rules/empty.rules \
  --set classification-file=/etc/suricata/classification.config \
  --set reference-config-file=/etc/suricata/reference.config \
  $SURICATA_EXTRA_ARGS
