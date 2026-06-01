#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SURICATA_BIN="${SURICATA_BIN:-$ROOT_DIR/streamtrident_services/capture/suricata/runtime/bin/suricata}"
BASE_CONF="${BASE_CONF:-$ROOT_DIR/streamtrident_services/capture/suricata/runtime/etc/suricata/suricata.yaml}"
CLASSIFICATION_CONF="${CLASSIFICATION_CONF:-$ROOT_DIR/streamtrident_services/capture/suricata/runtime/etc/suricata/classification.config}"
REFERENCE_CONF="${REFERENCE_CONF:-$ROOT_DIR/streamtrident_services/capture/suricata/runtime/etc/suricata/reference.config}"
RULES_FILE="${RULES_FILE:-$ROOT_DIR/streamtrident_services/capture/suricata/runtime/rules/empty.rules}"
PCAP="${PCAP:-$ROOT_DIR/suricata/qa/docker/pcaps/tls.pcap}"

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-16380}"
REDIS_KEY="${REDIS_KEY:-trident:test:cic_flow:app_proto}"
REDIS_MODE="${REDIS_MODE:-list}"
KEEP_REDIS="${KEEP_REDIS:-0}"

WORK_DIR="${WORK_DIR:-$(mktemp -d /tmp/trident-cic-app-proto.XXXXXX)}"
LOG_DIR="$WORK_DIR/logs"
LIVE_CONF="$WORK_DIR/suricata-cic-redis.yaml"
REDIS_CONTAINER="trident-cic-app-proto-test-$$"
STARTED_REDIS=0

cleanup() {
  if [[ "$STARTED_REDIS" == "1" && "$KEEP_REDIS" != "1" ]]; then
    docker rm -f "$REDIS_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ "${KEEP_WORK_DIR:-0}" != "1" ]]; then
    rm -rf "$WORK_DIR"
  else
    echo "kept work dir: $WORK_DIR"
  fi
}
trap cleanup EXIT

require_file() {
  local path="$1"
  if [[ ! -r "$path" ]]; then
    echo "missing readable file: $path" >&2
    exit 2
  fi
}

require_file "$SURICATA_BIN"
require_file "$BASE_CONF"
require_file "$CLASSIFICATION_CONF"
require_file "$REFERENCE_CONF"
require_file "$RULES_FILE"
require_file "$PCAP"
mkdir -p "$LOG_DIR"

python_redis() {
  python3 - "$REDIS_HOST" "$REDIS_PORT" "$@" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
args = sys.argv[3:]

def encode(parts):
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        data = str(part).encode()
        out.append(f"${len(data)}\r\n".encode())
        out.append(data + b"\r\n")
    return b"".join(out)

def read_line(sock):
    data = b""
    while not data.endswith(b"\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise EOFError("redis closed connection")
        data += chunk
    return data[:-2]

def read_resp(sock):
    prefix = sock.recv(1)
    if not prefix:
        raise EOFError("redis closed connection")
    if prefix == b"+":
        return read_line(sock).decode()
    if prefix == b"-":
        raise RuntimeError(read_line(sock).decode())
    if prefix == b":":
        return int(read_line(sock))
    if prefix == b"$":
        size = int(read_line(sock))
        if size < 0:
            return None
        data = b""
        while len(data) < size:
            data += sock.recv(size - len(data))
        sock.recv(2)
        return data.decode(errors="replace")
    if prefix == b"*":
        count = int(read_line(sock))
        return [read_resp(sock) for _ in range(count)]
    raise RuntimeError(f"unsupported redis prefix: {prefix!r}")

with socket.create_connection((host, port), timeout=3) as sock:
    sock.sendall(encode(args))
    result = read_resp(sock)

if isinstance(result, list):
    for item in result:
        print("" if item is None else item)
else:
    print("" if result is None else result)
PY
}

if ! python_redis PING >/dev/null 2>&1; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Redis is not reachable at $REDIS_HOST:$REDIS_PORT and docker is unavailable." >&2
    exit 2
  fi
  docker run --rm -d \
    --name "$REDIS_CONTAINER" \
    -p "$REDIS_HOST:$REDIS_PORT:6379" \
    redis:7-alpine >/dev/null
  STARTED_REDIS=1
  for _ in $(seq 1 30); do
    if python_redis PING >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
fi

python_redis DEL "$REDIS_KEY" >/dev/null

python3 - "$BASE_CONF" "$LIVE_CONF" "$REDIS_HOST" "$REDIS_PORT" "$REDIS_KEY" "$REDIS_MODE" <<'PY'
import sys
from pathlib import Path

base, out, redis_host, redis_port, redis_key, redis_mode = sys.argv[1:]
redis_mode = redis_mode.strip().lower()
if redis_mode not in {"list", "lpush", "stream", "xadd"}:
    raise SystemExit(f"unsupported REDIS_MODE: {redis_mode}")

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
            f"        mode: {redis_mode}",
            f"        key: {redis_key}",
            "      types:",
            "        - cic-flow:",
            "            enabled: yes",
            "            mode: cic-flowmeter",
            "            flow-timeout-us: 1000000",
            "            active-idle-threshold-us: 500000",
            "  - stats:",
            "      enabled: yes",
            "      filename: stats.log",
            "      append: no",
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

echo "suricata: $SURICATA_BIN"
sha256sum "$SURICATA_BIN"
echo "pcap: $PCAP"
echo "redis: $REDIS_HOST:$REDIS_PORT key=$REDIS_KEY mode=$REDIS_MODE"

"$SURICATA_BIN" -T -c "$LIVE_CONF" -l "$LOG_DIR" \
  -S "$RULES_FILE" \
  --set "classification-file=$CLASSIFICATION_CONF" \
  --set "reference-config-file=$REFERENCE_CONF" >/dev/null

"$SURICATA_BIN" -r "$PCAP" -c "$LIVE_CONF" -l "$LOG_DIR" -k none \
  -S "$RULES_FILE" \
  --set "classification-file=$CLASSIFICATION_CONF" \
  --set "reference-config-file=$REFERENCE_CONF" >/dev/null

python3 - "$REDIS_HOST" "$REDIS_PORT" "$REDIS_KEY" "$REDIS_MODE" <<'PY'
import json
import socket
import sys
from collections import Counter

host, port, key, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4].lower()

def encode(parts):
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        data = str(part).encode()
        out.append(f"${len(data)}\r\n".encode())
        out.append(data + b"\r\n")
    return b"".join(out)

def read_line(sock):
    data = b""
    while not data.endswith(b"\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise EOFError("redis closed connection")
        data += chunk
    return data[:-2]

def read_resp(sock):
    prefix = sock.recv(1)
    if prefix == b"+":
        return read_line(sock).decode()
    if prefix == b"-":
        raise RuntimeError(read_line(sock).decode())
    if prefix == b":":
        return int(read_line(sock))
    if prefix == b"$":
        size = int(read_line(sock))
        if size < 0:
            return None
        data = b""
        while len(data) < size:
            data += sock.recv(size - len(data))
        sock.recv(2)
        return data.decode(errors="replace")
    if prefix == b"*":
        return [read_resp(sock) for _ in range(int(read_line(sock)))]
    raise RuntimeError(f"unsupported redis prefix: {prefix!r}")

def redis(*parts):
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.sendall(encode(parts))
        return read_resp(sock)

kind = redis("TYPE", key)
if kind == "none":
    print("FAIL: no Redis events were written")
    sys.exit(1)

if kind == "list":
    rows = redis("LRANGE", key, "0", "-1")
elif kind == "stream":
    entries = redis("XRANGE", key, "-", "+")
    rows = []
    for entry in entries:
        fields = entry[1]
        pairs = dict(zip(fields[0::2], fields[1::2]))
        rows.append(pairs.get("message") or pairs.get("data") or json.dumps(pairs))
else:
    print(f"FAIL: unexpected Redis key type: {kind}")
    sys.exit(1)

events = []
parse_failed = 0
for row in rows:
    try:
        payload = json.loads(row)
    except Exception:
        parse_failed += 1
        continue
    if payload.get("event_type") == "cic_flow":
        events.append(payload)

with_field = [e for e in events if "app_proto" in e]
meaningful = [
    e for e in with_field
    if str(e.get("app_proto") or "").strip().lower() not in {"", "unknown", "none", "-"}
]
counts = Counter(str(e.get("app_proto", "<missing>")) for e in events)

print(f"redis_key_type={kind}")
print(f"raw_rows={len(rows)} cic_flow_events={len(events)} parse_failed={parse_failed}")
print(f"with_app_proto={len(with_field)} meaningful_app_proto={len(meaningful)}")
print("app_proto_counts=" + json.dumps(dict(counts.most_common()), sort_keys=True))

for event in events[:3]:
    sample = {
        "event_type": event.get("event_type"),
        "proto": event.get("proto"),
        "app_proto": event.get("app_proto", "<missing>"),
        "src_ip": event.get("src_ip"),
        "src_port": event.get("src_port"),
        "dest_ip": event.get("dest_ip"),
        "dest_port": event.get("dest_port"),
    }
    print("sample=" + json.dumps(sample, ensure_ascii=False, sort_keys=True))

if not events:
    print("FAIL: Redis has rows, but no cic_flow events")
    sys.exit(1)
if len(with_field) != len(events):
    print("FAIL: at least one cic_flow event is missing app_proto")
    sys.exit(1)
if not meaningful:
    print("WARN: app_proto field exists, but this pcap produced only unknown/empty values")
    sys.exit(0)
print("PASS: cic_flow Redis events include application-layer protocol")
PY
