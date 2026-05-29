COMPOSE ?= docker compose
SERVICE ?=
LOGS ?= trident-api trident-worker suricata-cic suricata-agent

.PHONY: help up down ps build rebuild capture-up capture-check-redis trident-up trident-test-up trident-test-down trident-test-coldstart trident-test-inference trident-test-worker-logs capture-down trident-down restart restart-trident restart-capture logs logs-all migrate worker api suricata suricata-agent clean

ANALYSIS_DIR := analysis
ANALYSIS_ENV_FILE := .env.test
ANALYSIS_COMPOSE := -f compose.yaml -f compose.test.yaml --env-file $(ANALYSIS_ENV_FILE)
ANALYSIS_COMPOSE_COLDSTART := $(ANALYSIS_COMPOSE) -f compose.coldstart.test.yaml
ANALYSIS_COMPOSE_INFERENCE := $(ANALYSIS_COMPOSE) -f compose.inference.test.yaml

help:
	@printf '%s\n' \
		'Targets:' \
		'  make up                Start all default services' \
		'  make build             Build service images' \
		'  make rebuild           Build images and recreate containers' \
		'  make capture-up        Start capture stack from capture/compose.yaml' \
		'  make capture-check-redis  Verify Redis flow ingest on capture host' \
		'  make trident-up        Start Trident stack from analysis/compose.yaml' \
		'  make trident-test-up        Start analysis test stack (deps + api + inference worker)' \
		'  make trident-test-coldstart Recreate test worker in cold_start mode' \
		'  make trident-test-inference Recreate test worker in inference mode' \
		'  make trident-test-worker-logs Tail test worker log (cold_start / inference events)' \
		'  make capture-down           Stop capture stack' \
		'  make trident-down           Stop Trident stack' \
		'  make trident-test-down      Stop analysis test stack' \
		'  make restart           Restart one service: make restart SERVICE=trident-api' \
		'  make restart-trident   Rebuild/recreate trident-migrate, trident-worker, trident-api' \
		'  make restart-capture   Rebuild/recreate Suricata CIC capture service' \
		'  make logs              Follow API/worker logs, or set LOGS="service ..."' \
		'  make logs-all          Follow all compose logs' \
		'  make ps                Show service status' \
		'  make down              Stop containers' \
		'  make migrate           Run trident migration service' \
		'  make worker            Recreate trident worker' \
		'  make api               Recreate trident API' \
		'  make suricata          Recreate Suricata CIC capture service' \
		'  make suricata-agent    Recreate Suricata local control agent' \
		'  make clean             Stop containers and remove volumes'

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

rebuild:
	$(COMPOSE) up -d --build --force-recreate

capture-up:
	cd capture && ./start.sh

capture-check-redis:
	cd capture && ./check-redis-flow.sh

trident-up:
	cd analysis && ./start.sh

trident-test-up:
	cd $(ANALYSIS_DIR) && ./start-test.sh

trident-test-coldstart:
	cd $(ANALYSIS_DIR) && set -a && . ./$(ANALYSIS_ENV_FILE) && set +a && \
		export COMPOSE_PROJECT_NAME="$${COMPOSE_PROJECT_NAME:-streamtrident-test}" && \
		$(COMPOSE) $(ANALYSIS_COMPOSE_COLDSTART) up -d --force-recreate trident-worker

trident-test-inference:
	cd $(ANALYSIS_DIR) && set -a && . ./$(ANALYSIS_ENV_FILE) && set +a && \
		export COMPOSE_PROJECT_NAME="$${COMPOSE_PROJECT_NAME:-streamtrident-test}" && \
		$(COMPOSE) $(ANALYSIS_COMPOSE_INFERENCE) up -d --force-recreate trident-worker

trident-test-worker-logs:
	tail -f $(ANALYSIS_DIR)/trident/logs-test/worker.log

trident-test-down:
	cd $(ANALYSIS_DIR) && ./stop-test.sh

capture-down:
	cd capture && docker compose -f compose.yaml down

trident-down:
	cd analysis && docker compose -f compose.yaml down

restart:
	@if [ -z "$(SERVICE)" ]; then \
		echo 'Set SERVICE, for example: make restart SERVICE=trident-api'; \
		exit 2; \
	fi
	$(COMPOSE) up -d --build --force-recreate $(SERVICE)

restart-trident:
	$(COMPOSE) up -d --build --force-recreate trident-migrate trident-worker trident-api

restart-capture:
	$(COMPOSE) up -d --build --force-recreate suricata-agent suricata-cic

logs:
	$(COMPOSE) logs -f --tail=200 $(LOGS)

logs-all:
	$(COMPOSE) logs -f --tail=200

migrate:
	$(COMPOSE) up --build --force-recreate trident-migrate

worker:
	$(COMPOSE) up -d --build --force-recreate trident-worker

api:
	$(COMPOSE) up -d --build --force-recreate trident-api

suricata:
	$(COMPOSE) up -d --build --force-recreate suricata-cic

suricata-agent:
	$(COMPOSE) up -d --build --force-recreate suricata-agent

clean:
	$(COMPOSE) down -v
