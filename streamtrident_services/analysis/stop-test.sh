#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE="${ENV_FILE:-.env.test}"
COMPOSE_FILES=(-f compose.yaml -f compose.test.yaml)

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-streamtrident-test}"

docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" down

echo "trident test stack stopped (project: $COMPOSE_PROJECT_NAME)"
