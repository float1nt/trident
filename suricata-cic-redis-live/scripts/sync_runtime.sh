#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SURICATA_SRC="${SURICATA_SRC:-/home/Suricata/suricata}"

install -d "$ROOT_DIR/runtime/bin" \
  "$ROOT_DIR/runtime/etc/suricata" \
  "$ROOT_DIR/runtime/rules"

install -m 0755 "$SURICATA_SRC/src/suricata" "$ROOT_DIR/runtime/bin/suricata"
install -m 0644 "$SURICATA_SRC/suricata.yaml" "$ROOT_DIR/runtime/etc/suricata/suricata.yaml"
install -m 0644 "$SURICATA_SRC/etc/classification.config" \
  "$ROOT_DIR/runtime/etc/suricata/classification.config"
install -m 0644 "$SURICATA_SRC/etc/reference.config" \
  "$ROOT_DIR/runtime/etc/suricata/reference.config"
touch "$ROOT_DIR/runtime/rules/empty.rules"

echo "synced modified Suricata runtime into $ROOT_DIR/runtime"
echo
echo "binary:"
"$ROOT_DIR/runtime/bin/suricata" --build-info | sed -n '1,35p'
echo
if ldd "$ROOT_DIR/runtime/bin/suricata" | grep -q hiredis; then
  echo "redis backend check: linked with hiredis"
else
  echo "redis backend check: WARNING not linked with hiredis; rebuild Suricata with --enable-hiredis before using Redis output" >&2
fi
