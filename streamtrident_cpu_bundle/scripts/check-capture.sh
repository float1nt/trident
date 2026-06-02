#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

load_deploy_env

REDIS_HOST="${CAPTURE_REDIS_HOST:-${CAPTURE_HOST:-127.0.0.1}}"
REDIS_PORT="${CAPTURE_REDIS_PORT:-${REDIS_HOST_PORT:-16379}}"
REDIS_KEY="${SURICATA_REDIS_STREAM:-suricata:cic_flow}"

echo "采集端 Redis: ${REDIS_HOST}:${REDIS_PORT}"
echo "采集队列 Key: ${REDIS_KEY}"
echo

echo "[1/4] 检查 Redis 连通性"
if ! docker run --rm redis:7-alpine redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping; then
  echo "Redis 无法连接。请检查采集端 IP、端口、防火墙和 Redis 容器状态。" >&2
  exit 2
fi

echo
echo "[2/4] 检查队列长度"
QUEUE_LEN="$(docker run --rm redis:7-alpine redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" LLEN "${REDIS_KEY}")"
echo "LLEN ${REDIS_KEY} = ${QUEUE_LEN}"

echo
echo "[3/4] 查看最新一条 flow"
LATEST="$(docker run --rm redis:7-alpine redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" LRANGE "${REDIS_KEY}" -1 -1)"
if [ -n "${LATEST}" ]; then
  printf '%s\n' "${LATEST}" | head -c 1000
  echo
else
  echo "队列里暂时没有 flow 数据。"
fi

echo
echo "[4/4] 检查本机采集容器状态"
if docker ps --format '{{.Names}} {{.Status}}' | grep -E '^(streamtrident-redis|streamtrident-suricata-cic|streamtrident-suricata-agent) '; then
  :
else
  echo "本机未发现采集容器。若你在分析端运行本脚本，这是正常的；请在采集端运行可查看容器状态。"
fi

echo
if [ "${QUEUE_LEN}" -gt 0 ]; then
  echo "结论：采集端 Redis 中存在 flow 数据。"
else
  echo "结论：当前未看到 flow 数据。请检查 SURICATA_IFACE 是否为真实抓包网卡，以及采集端是否有网络流量。"
fi
