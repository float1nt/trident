#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

set -a
[ -f .env ] && . ./.env
set +a

REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_STREAM="${REDIS_STREAM:-suricata:cic_flow}"

echo "containers"
docker compose ps

echo
echo "redis stream"
docker run --rm --network host redis:7-alpine redis-cli -h 127.0.0.1 -p "$REDIS_PORT" XLEN "$REDIS_STREAM" || true
docker run --rm --network host redis:7-alpine redis-cli -h 127.0.0.1 -p "$REDIS_PORT" XINFO STREAM "$REDIS_STREAM" || true

echo
echo "last cic_flow event"
docker run --rm --network host redis:7-alpine redis-cli -h 127.0.0.1 -p "$REDIS_PORT" XREVRANGE "$REDIS_STREAM" + - COUNT 1 || true

echo
echo "suricata container logs"
docker logs --tail 80 suricata-cic-live || true

echo
echo "suricata.log tail"
tail -n 80 "$ROOT_DIR/logs/suricata.log" 2>/dev/null || true

echo
echo "stats.log tail"
tail -n 80 "$ROOT_DIR/logs/stats.log" 2>/dev/null || true
