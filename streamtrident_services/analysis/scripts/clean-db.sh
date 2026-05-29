#!/usr/bin/env bash
# 清空 analysis 栈 Postgres + ClickHouse 数据（删除数据卷并重新 migrate）。
# 用法: ./scripts/clean-db.sh test|prod
# 可选: CLEAN_MODELS=0 保留 trident-models 卷（仅清库表）
set -euo pipefail

MODE="${1:-}"
if [ "$MODE" != "test" ] && [ "$MODE" != "prod" ]; then
  echo "usage: $0 test|prod"
  exit 2
fi

cd "$(dirname "$0")/.."

if [ "$MODE" = "test" ]; then
  ENV_FILE="${ENV_FILE:-.env.test}"
  COMPOSE_FILES=(-f compose.yaml -f compose.test.yaml)
  DEFAULT_PROJECT="streamtrident-test"
else
  ENV_FILE="${ENV_FILE:-.env}"
  COMPOSE_FILES=(-f compose.yaml)
  DEFAULT_PROJECT="analysis"
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "config file not found: analysis/$ENV_FILE"
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$DEFAULT_PROJECT}"
CLEAN_MODELS="${CLEAN_MODELS:-1}"

echo "==> clean-db ($MODE) project=$COMPOSE_PROJECT_NAME env=$ENV_FILE"

docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" stop trident-worker trident-api 2>/dev/null || true

if [ "$CLEAN_MODELS" = "1" ]; then
  echo "==> removing volumes (postgres, clickhouse, trident-models)"
  docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" down -v
else
  echo "==> removing postgres + clickhouse volumes only (keep trident-models)"
  docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" stop clickhouse postgres 2>/dev/null || true
  for vol in "${COMPOSE_PROJECT_NAME}_postgres-data" "${COMPOSE_PROJECT_NAME}_clickhouse-data"; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
      docker volume rm "$vol"
      echo "removed volume: $vol"
    fi
  done
fi

echo "==> starting postgres + clickhouse"
docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" up -d clickhouse postgres

echo "==> waiting for healthy"
for i in $(seq 1 60); do
  if docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" ps clickhouse postgres 2>/dev/null | grep -q healthy; then
    if [ "$(docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" ps clickhouse postgres 2>/dev/null | grep -c healthy || true)" -ge 2 ]; then
      break
    fi
  fi
  sleep 2
done

echo "==> running migrate"
docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" up --build --force-recreate trident-migrate

cat <<EOF

database cleaned ($MODE)
  project: $COMPOSE_PROJECT_NAME
  postgres / clickhouse: empty schema via trident-migrate
  worker/api: stopped (start from streamtrident_services with make prod-start-* or make test-start-*)

EOF
