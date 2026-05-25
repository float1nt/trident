#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  detected_iface="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"
  if [ -n "${detected_iface:-}" ]; then
    sed -i "s/^IFACE=.*/IFACE=${detected_iface}/" .env
  fi
  echo "created .env; review it before production use"
fi

set -a
. ./.env
set +a

if ! docker image inspect suricata-cic-live:local >/dev/null 2>&1; then
  "$ROOT_DIR/scripts/build_image.sh"
fi

docker compose up -d redis
echo "waiting for redis"
for _ in $(seq 1 30); do
  if docker run --rm --network host redis:7-alpine redis-cli -h 127.0.0.1 -p "${REDIS_PORT:-6379}" PING >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

docker compose up -d suricata-cic
docker compose ps
