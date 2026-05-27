COMPOSE ?= docker compose
SERVICE ?=
LOGS ?= trident-api trident-worker suricata-cic

.PHONY: help up down ps build rebuild restart restart-trident restart-capture logs logs-all migrate worker api suricata clean

help:
	@printf '%s\n' \
		'Targets:' \
		'  make up                Start all default services' \
		'  make build             Build service images' \
		'  make rebuild           Build images and recreate containers' \
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

restart:
	@if [ -z "$(SERVICE)" ]; then \
		echo 'Set SERVICE, for example: make restart SERVICE=trident-api'; \
		exit 2; \
	fi
	$(COMPOSE) up -d --build --force-recreate $(SERVICE)

restart-trident:
	$(COMPOSE) up -d --build --force-recreate trident-migrate trident-worker trident-api

restart-capture:
	$(COMPOSE) up -d --build --force-recreate suricata-cic

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

clean:
	$(COMPOSE) down -v
