#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATTERN='from trident_stream|import trident_stream|from learner_qualification|import learner_qualification|from scripts\.|import scripts\.'
if rg -q "$PATTERN" "$ROOT/trident_demo" --glob '*.py' 2>/dev/null; then
  echo "FAIL: trident_demo Python files import legacy modules" >&2
  rg "$PATTERN" "$ROOT/trident_demo" --glob '*.py' || true
  exit 1
fi
if rg -q 'subprocess.*(scripts/|main\.py)' "$ROOT/trident_demo" --glob '*.py' 2>/dev/null; then
  echo "FAIL: trident_demo subprocess-calls legacy scripts" >&2
  exit 1
fi
echo "OK: trident_demo is decoupled from legacy imports"
