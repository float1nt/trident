#!/usr/bin/env bash
# 重置 analysis 侧数据：停止分析侧相关容器，删除 Postgres / ClickHouse / 模型卷，
# 然后重新创建数据库空表结构。
# 用法: ./scripts/reset-analysis-data.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "${SCRIPT_DIR}/common.sh"

CONFIRM_TEXT="RESET ANALYSIS"
echo "This will erase analysis-side data (postgres, clickhouse, model volumes) and recreate empty schema."
echo "Type exactly: ${CONFIRM_TEXT}"
read -r user_input
if [ "${user_input}" != "${CONFIRM_TEXT}" ]; then
  echo "aborted"
  exit 1
fi

load_deploy_env
prepare_runtime

echo "==> stopping all stack services"
for file in \
  "${RUNTIME_DIR}/analysis/compose.yaml" \
  "${RUNTIME_DIR}/capture/compose.yaml" \
  "${RUNTIME_DIR}/ui/compose.yaml"; do
  if [ -f "${file}" ]; then
    docker compose -f "${file}" down >/dev/null 2>&1 || true
  fi
done

echo "==> removing analysis volumes (postgres, clickhouse, trident-models)"
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" down -v >/dev/null 2>&1 || true

echo "==> recreating postgres + clickhouse"
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up -d clickhouse postgres

echo "==> waiting for healthy"
for _ in $(seq 1 60); do
  healthy_count="$(docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" ps clickhouse postgres 2>/dev/null | grep -c healthy || true)"
  if [ "${healthy_count}" -ge 2 ]; then
    break
  fi
  sleep 2
done

echo "==> running migrate"
docker compose -f "${RUNTIME_DIR}/analysis/compose.yaml" up --build --force-recreate trident-migrate

echo "analysis side reset complete"
echo "  databases: empty schema"
echo "  models: cleared"
echo "  worker/api: stopped"
