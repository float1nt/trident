#!/usr/bin/env bash
set -euo pipefail

IFACE="${IFACE:-eth0}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-16379}"
REDIS_STREAM="${REDIS_STREAM:-suricata:cic_flow}"
REDIS_OUTPUT_MODE="${REDIS_OUTPUT_MODE:-list}"
REDIS_LIST_MAXLEN="${REDIS_LIST_MAXLEN:-100000}"
REDIS_STREAM_MAXLEN="${REDIS_STREAM_MAXLEN:-1000000}"
CIC_MODE="${CIC_MODE:-cic-flowmeter}"
CIC_FLOW_TIMEOUT_US="${CIC_FLOW_TIMEOUT_US:-120000000}"
CIC_ACTIVE_IDLE_THRESHOLD_US="${CIC_ACTIVE_IDLE_THRESHOLD_US:-5000000}"
CIC_PAYLOAD_SAMPLE_ENABLED="${CIC_PAYLOAD_SAMPLE_ENABLED:-true}"
CIC_PAYLOAD_SAMPLE_MAX_BYTES="${CIC_PAYLOAD_SAMPLE_MAX_BYTES:-256}"
SURICATA_CAPTURE_FILTER_CONFIG="${SURICATA_CAPTURE_FILTER_CONFIG:-}"
SURICATA_TCP_NEW_TIMEOUT="${SURICATA_TCP_NEW_TIMEOUT:-10}"
SURICATA_TCP_EMERGENCY_NEW_TIMEOUT="${SURICATA_TCP_EMERGENCY_NEW_TIMEOUT:-1}"
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

python3 - "$BASE_CONF" "$LIVE_CONF" "$IFACE" "$REDIS_HOST" "$REDIS_PORT" "$REDIS_STREAM" "$REDIS_OUTPUT_MODE" \
  "$REDIS_LIST_MAXLEN" "$REDIS_STREAM_MAXLEN" "$CIC_MODE" "$CIC_FLOW_TIMEOUT_US" \
  "$CIC_ACTIVE_IDLE_THRESHOLD_US" "$CIC_PAYLOAD_SAMPLE_ENABLED" "$CIC_PAYLOAD_SAMPLE_MAX_BYTES" \
  "$SURICATA_FILTER_CONFIG" "$SURICATA_CAPTURE_FILTER_CONFIG" \
  "$SURICATA_TCP_NEW_TIMEOUT" "$SURICATA_TCP_EMERGENCY_NEW_TIMEOUT" <<'PY'
import ipaddress
import json
import sys
from pathlib import Path

base, out, iface, redis_host, redis_port, redis_stream, redis_mode, redis_list_maxlen, redis_maxlen, cic_mode, flow_timeout, active_idle, payload_sample_enabled, payload_sample_max_bytes, filter_path, capture_filter_path, tcp_new_timeout, tcp_emergency_new_timeout = sys.argv[1:]

def load_json_config(path: str, label: str) -> dict:
    if not path:
        return {}
    target = Path(path)
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid {label} config: {path}")
    return payload

def load_filter(path: str) -> dict:
    return load_json_config(path, "Suricata filter")

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

def bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def ip_network_terms(items: list[dict], direction: str) -> list[str] | None:
    terms: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        start = str(item.get("startIp", "")).strip()
        end = str(item.get("endIp", "")).strip()
        if not start or not end:
            continue
        start_ip = ipaddress.IPv4Address(start)
        end_ip = ipaddress.IPv4Address(end)
        if int(start_ip) > int(end_ip):
            raise SystemExit(f"invalid capture filter IP range: {start}-{end}")
        if start_ip == ipaddress.IPv4Address("0.0.0.0") and end_ip == ipaddress.IPv4Address("255.255.255.255"):
            return None
        for network in ipaddress.summarize_address_range(start_ip, end_ip):
            if network.prefixlen == 32:
                terms.append(f"{direction} host {network.network_address}")
            else:
                terms.append(f"{direction} net {network.with_prefixlen}")
    return terms

def bpf_or(terms: list[str] | None) -> str:
    if terms is None or not terms:
        return ""
    return terms[0] if len(terms) == 1 else "(" + " or ".join(terms) + ")"

def bpf_and(terms: list[str]) -> str:
    active = [term for term in terms if term]
    if not active:
        return ""
    return active[0] if len(active) == 1 else "(" + " and ".join(active) + ")"

def protocol_bpf(protocols: list[str]) -> str:
    terms: set[str] = set()
    for value in protocols:
        proto = value.strip().lower()
        if proto == "tcp":
            terms.add("tcp")
        elif proto == "udp":
            terms.add("udp")
        elif proto in {"icmp", "icmpv4"}:
            terms.add("icmp")
        elif proto == "icmpv6":
            terms.add("icmp6")
        elif proto in {"http", "https", "tls", "ssh", "smb", "smb2", "rdp", "ftp"}:
            terms.add("tcp")
        elif proto == "dns":
            terms.add("tcp")
            terms.add("udp")
    ordered = [term for term in ("tcp", "udp", "icmp", "icmp6") if term in terms]
    return bpf_or(ordered)

def capture_bpf(payload: dict) -> str:
    if not payload or not bool_value(payload.get("enabled", True)):
        return ""
    src_items = payload.get("sourceIpRanges", []) or []
    dst_items = payload.get("destIpRanges", []) or []
    src_as_src = bpf_or(ip_network_terms(src_items, "src"))
    src_as_dst = bpf_or(ip_network_terms(src_items, "dst"))
    dst_as_src = bpf_or(ip_network_terms(dst_items, "src"))
    dst_as_dst = bpf_or(ip_network_terms(dst_items, "dst"))

    ip_clause = ""
    if src_as_src and dst_as_dst:
        forward = bpf_and([src_as_src, dst_as_dst])
        reverse = bpf_and([dst_as_src, src_as_dst])
        ip_clause = bpf_or([forward, reverse])
    elif src_as_src:
        ip_clause = bpf_or([src_as_src, src_as_dst])
    elif dst_as_dst:
        ip_clause = bpf_or([dst_as_src, dst_as_dst])

    proto_clause = protocol_bpf(scalar_values(payload, "protocols"))
    extra = str(payload.get("extraBpf", "") or payload.get("extra_bpf", "")).strip()
    return bpf_and([ip_clause, proto_clause, extra])

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
capture_filter_payload = load_json_config(capture_filter_path, "Suricata capture filter")
capture_filter_bpf = capture_bpf(capture_filter_payload)
redis_mode = redis_mode.strip().lower()
if redis_mode not in {"list", "lpush", "stream", "xadd"}:
    raise SystemExit(f"unsupported Redis output mode: {redis_mode}")
lines = Path(base).read_text(encoding="utf-8", errors="replace").splitlines()
result = []
skip = False
in_af_packet = False
af_packet_interface_done = False
in_tcp_timeouts = False
for line in lines:
    if line == "af-packet:":
        in_af_packet = True
        af_packet_interface_done = False
        result.append(line)
        continue
    if in_af_packet and line and not line.startswith(" ") and not line.startswith("-"):
        in_af_packet = False
    if in_af_packet and not af_packet_interface_done and line.startswith("  - interface:"):
        result.append(f"  - interface: {iface}")
        if capture_filter_bpf:
            result.append(f"    bpf-filter: {json.dumps(capture_filter_bpf)}")
        af_packet_interface_done = True
        continue
    if in_af_packet and af_packet_interface_done and capture_filter_bpf and line.strip().startswith("bpf-filter:"):
        continue
    if line == "  tcp:":
        in_tcp_timeouts = True
        result.append(line)
        continue
    if in_tcp_timeouts and line.startswith("  ") and not line.startswith("    ") and line != "  tcp:":
        in_tcp_timeouts = False
    if in_tcp_timeouts and line.strip().startswith("new:"):
        result.append(f"    new: {tcp_new_timeout}")
        continue
    if in_tcp_timeouts and line.strip().startswith("emergency-new:"):
        result.append(f"    emergency-new: {tcp_emergency_new_timeout}")
        continue
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
            f"        mode: {redis_mode}",
            f"        key: {redis_stream}",
        ])
        if redis_mode in {"list", "lpush", "rpush"}:
            result.append(f"        list-maxlen: {redis_list_maxlen}")
        if redis_mode in {"stream", "xadd"}:
            result.append(f"        stream-maxlen: {redis_maxlen}")
        result.extend([
            "      types:",
            "        - cic-flow:",
            "            enabled: yes",
            f"            mode: {cic_mode}",
            f"            flow-timeout-us: {flow_timeout}",
            f"            active-idle-threshold-us: {active_idle}",
            f"            payload-sample-enabled: {payload_sample_enabled}",
            f"            payload-sample-max-bytes: {payload_sample_max_bytes}",
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
echo "  redis_output_mode=$REDIS_OUTPUT_MODE"
echo "  redis_list_maxlen=$REDIS_LIST_MAXLEN"
echo "  capture_filter_config=${SURICATA_CAPTURE_FILTER_CONFIG:-<none>}"
echo "  tcp_new_timeout=$SURICATA_TCP_NEW_TIMEOUT"
echo "  tcp_emergency_new_timeout=$SURICATA_TCP_EMERGENCY_NEW_TIMEOUT"
echo "  mode=$CIC_MODE"
echo "  payload_sample_enabled=$CIC_PAYLOAD_SAMPLE_ENABLED"
echo "  payload_sample_max_bytes=$CIC_PAYLOAD_SAMPLE_MAX_BYTES"
echo "  log_dir=$LOG_DIR"
if [ -n "$SURICATA_FILTER_CONFIG" ] && [ -r "$SURICATA_FILTER_CONFIG" ]; then
  echo "  filter_config=$SURICATA_FILTER_CONFIG"
else
  echo "  filter_config=<none>"
fi

redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" PING >/dev/null
KEY_TYPE="$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" TYPE "$REDIS_STREAM" | tr -d '\r')"
case "$REDIS_OUTPUT_MODE:$KEY_TYPE" in
  list:none|list:list|lpush:none|lpush:list|stream:none|stream:stream|xadd:none|xadd:stream)
    ;;
  *)
    echo "redis key type mismatch: key=$REDIS_STREAM type=$KEY_TYPE output_mode=$REDIS_OUTPUT_MODE" >&2
    echo "delete or rename the old key before switching queue modes" >&2
    exit 1
    ;;
esac

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
