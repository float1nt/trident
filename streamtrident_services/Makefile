COMPOSE ?= docker compose

.PHONY: help \
	prod-start-coldstart prod-start-inference prod-rebuild-coldstart prod-rebuild-inference prod-export-coldstart prod-stop prod-clean-db prod-logs \
	prod-import-coldstart \
	test-start-coldstart test-start-inference test-rebuild-coldstart test-rebuild-inference test-export-coldstart test-import-coldstart test-stop test-clean-db test-logs \
	capture-start capture-stop capture-check capture-logs

ANALYSIS_DIR := analysis
ANALYSIS_PROD_ENV_FILE ?= .env
ANALYSIS_TEST_ENV_FILE ?= .env.test
ANALYSIS_PROD_PROJECT ?= analysis
ANALYSIS_TEST_PROJECT ?= streamtrident-test
ANALYSIS_PROD_API_PORT ?= 8090
ANALYSIS_TEST_API_PORT ?= 9090
ANALYSIS_SERVICES := clickhouse postgres trident-migrate trident-api trident-worker
ANALYSIS_PROD_COMPOSE := -f compose.yaml
ANALYSIS_TEST_COMPOSE := -f compose.yaml -f compose.test.yaml
ANALYSIS_COLDSTART_OVERRIDE := -f compose.coldstart.yaml
ANALYSIS_INFERENCE_OVERRIDE := -f compose.inference.yaml
DEVICE_TYPE ?= cuda
SESSION_ID ?= accuracy-mixed_attack_panel-aa2b640d82
ARTIFACT ?= coldstart-$(SESSION_ID).tar.gz

define analysis_up
	cd $(ANALYSIS_DIR) && \
		if [ ! -f "$(1)" ]; then \
			echo "缺少配置文件: analysis/$(1)"; \
			exit 2; \
		fi && \
		set -a && . ./$(1) && set +a && \
		export COMPOSE_PROJECT_NAME="$${COMPOSE_PROJECT_NAME:-$(2)}" && \
		export DEVICE_TYPE="$${DEVICE_TYPE:-$(DEVICE_TYPE)}" && \
		export CAPTURE_REDIS_HOST="$${CAPTURE_REDIS_HOST:-host.docker.internal}" && \
		export CAPTURE_REDIS_PORT="$${CAPTURE_REDIS_PORT:-16379}" && \
		export TRIDENT_SURICATA_AGENT_URLS="$${TRIDENT_SURICATA_AGENT_URLS:-http://host.docker.internal:19100}" && \
		export TRIDENT_API_HOST_PORT="$${TRIDENT_API_HOST_PORT:-$(3)}" && \
		CPU_COMPOSE="" && \
		if [ "$$DEVICE_TYPE" = "cpu" ]; then CPU_COMPOSE="-f compose.cpu.yaml"; fi && \
		mkdir -p $(4) && \
		$(COMPOSE) --env-file $(1) $(5) $(6) $$CPU_COMPOSE up -d $(10) $(ANALYSIS_SERVICES) && \
		printf '%s\n' \
			"分析侧已启动: 环境=$(8), 模式=$(7), project=$$COMPOSE_PROJECT_NAME, device=$$DEVICE_TYPE" \
			"  API:          0.0.0.0:$$TRIDENT_API_HOST_PORT" \
			"  Capture Redis: $$CAPTURE_REDIS_HOST:$$CAPTURE_REDIS_PORT" \
			"  Suricata API:  $$TRIDENT_SURICATA_AGENT_URLS" \
			"  日志:          make $(9)"
endef

define analysis_down
	cd $(ANALYSIS_DIR) && \
		if [ ! -f "$(1)" ]; then \
			echo "缺少配置文件: analysis/$(1)"; \
			exit 2; \
		fi && \
		set -a && . ./$(1) && set +a && \
		export COMPOSE_PROJECT_NAME="$${COMPOSE_PROJECT_NAME:-$(2)}" && \
		$(COMPOSE) --env-file $(1) $(3) down
endef

define analysis_export_coldstart
	cd $(ANALYSIS_DIR) && \
		if [ ! -f "$(1)" ]; then \
			echo "缺少配置文件: analysis/$(1)"; \
			exit 2; \
		fi && \
		set -a && . ./$(1) && set +a && \
		export COMPOSE_PROJECT_NAME="$${COMPOSE_PROJECT_NAME:-$(2)}" && \
		export DEVICE_TYPE="$${DEVICE_TYPE:-$(DEVICE_TYPE)}" && \
		CPU_COMPOSE="" && \
		if [ "$$DEVICE_TYPE" = "cpu" ]; then CPU_COMPOSE="-f compose.cpu.yaml"; fi && \
		mkdir -p $(4) && \
		$(COMPOSE) --env-file $(1) $(3) $$CPU_COMPOSE exec -T trident-api \
			python -m app.coldstart_artifact export \
				--config config/trident.yaml \
				--session-id "$(SESSION_ID)" \
				--output "/var/lib/trident/artifacts/$(ARTIFACT)" && \
		printf '%s\n' \
			"冷启动良性学习器已导出: analysis/$(4)/$(ARTIFACT)" \
			"  环境: $(5)" \
			"  session_id: $(SESSION_ID)"
endef

define analysis_import_coldstart
	cd $(ANALYSIS_DIR) && \
		if [ ! -f "$(1)" ]; then \
			echo "缺少配置文件: analysis/$(1)"; \
			exit 2; \
		fi && \
		if [ ! -f "$(4)/$(ARTIFACT)" ]; then \
			echo "缺少冷启动 artifact: analysis/$(4)/$(ARTIFACT)"; \
			exit 2; \
		fi && \
		set -a && . ./$(1) && set +a && \
		export COMPOSE_PROJECT_NAME="$${COMPOSE_PROJECT_NAME:-$(2)}" && \
		export DEVICE_TYPE="$${DEVICE_TYPE:-$(DEVICE_TYPE)}" && \
		CPU_COMPOSE="" && \
		if [ "$$DEVICE_TYPE" = "cpu" ]; then CPU_COMPOSE="-f compose.cpu.yaml"; fi && \
		$(COMPOSE) --env-file $(1) $(3) $$CPU_COMPOSE exec -T trident-api \
			python -m app.coldstart_artifact import \
				--config config/trident.yaml \
				--artifact "/var/lib/trident/artifacts/$(ARTIFACT)" \
				--target-session-id "$(SESSION_ID)" && \
		printf '%s\n' \
			"冷启动学习器已导入: analysis/$(4)/$(ARTIFACT)" \
			"  环境: $(5)" \
			"  session_id: $(SESSION_ID)"
endef

help:
	@printf '%s\n' \
		'StreamTrident 运维命令' \
		'' \
		'生产环境 analysis/.env:' \
		'  make prod-start-coldstart     生产-启动完整分析侧，worker=冷启动' \
		'  make prod-start-inference     生产-启动完整分析侧，worker=推理' \
		'  make prod-rebuild-coldstart   生产-重建完整分析侧，worker=冷启动' \
		'  make prod-rebuild-inference   生产-重建完整分析侧，worker=推理' \
		'  make prod-export-coldstart    生产-导出冷启动生成的 COLD_* 良性学习器' \
		'  make prod-import-coldstart    生产-导入冷启动生成的 COLD_* 良性学习器' \
		'  make prod-stop                生产-停止分析侧' \
		'  make prod-clean-db            生产-清空 Postgres/ClickHouse 和模型卷并重新迁移' \
		'  make prod-logs                生产-查看 worker 日志' \
		'' \
		'测试环境 analysis/.env.test:' \
		'  make test-start-coldstart     测试-启动完整分析侧，worker=冷启动' \
		'  make test-start-inference     测试-启动完整分析侧，worker=推理' \
		'  make test-rebuild-coldstart   测试-重建完整分析侧，worker=冷启动' \
		'  make test-rebuild-inference   测试-重建完整分析侧，worker=推理' \
		'  make test-export-coldstart    测试-导出冷启动生成的 COLD_* 良性学习器' \
		'  make test-import-coldstart    测试-导入冷启动生成的 COLD_* 良性学习器' \
		'  make test-stop                测试-停止分析侧' \
		'  make test-clean-db            测试-清空 Postgres/ClickHouse 和模型卷并重新迁移' \
		'  make test-logs                测试-查看 worker 日志' \
		'' \
		'GPU 构建 (默认 DEVICE_TYPE=cuda, 镜像: pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime):' \
		'  DEVICE_TYPE=cuda make test-rebuild-inference              CUDA 重建 (RTX 50 系需 cu128)' \
		'  DEVICE_TYPE=cpu make test-rebuild-inference               CPU 重建' \
		'' \
		'采集侧:' \
		'  make capture-start            启动采集侧 Redis/Suricata/agent' \
		'  make capture-stop             停止采集侧' \
		'  make capture-check            检查采集侧 Redis 流量写入' \
		'  make capture-logs             查看采集侧日志' \
		'' \
		'常用流程:' \
		'  1. make test-start-coldstart' \
		'  2. 等待日志出现 cold_start_complete' \
		'  3. make test-export-coldstart' \
		'  4. make test-start-inference' \
		'' \
		'导出参数:' \
		'  make test-export-coldstart SESSION_ID=... ARTIFACT=coldstart.tar.gz' \
		'导入参数:' \
		'  make test-import-coldstart SESSION_ID=... ARTIFACT=coldstart.tar.gz'

prod-start-coldstart:
	$(call analysis_up,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_API_PORT),trident/logs,$(ANALYSIS_PROD_COMPOSE),$(ANALYSIS_COLDSTART_OVERRIDE),cold_start,生产,prod-logs,--build)

prod-start-inference:
	$(call analysis_up,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_API_PORT),trident/logs,$(ANALYSIS_PROD_COMPOSE),$(ANALYSIS_INFERENCE_OVERRIDE),inference,生产,prod-logs,--build)

prod-rebuild-coldstart:
	$(call analysis_up,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_API_PORT),trident/logs,$(ANALYSIS_PROD_COMPOSE),$(ANALYSIS_COLDSTART_OVERRIDE),cold_start,生产,prod-logs,--build --force-recreate)

prod-rebuild-inference:
	$(call analysis_up,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_API_PORT),trident/logs,$(ANALYSIS_PROD_COMPOSE),$(ANALYSIS_INFERENCE_OVERRIDE),inference,生产,prod-logs,--build --force-recreate)

prod-export-coldstart:
	$(call analysis_export_coldstart,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_COMPOSE),trident/artifacts,生产)

prod-import-coldstart:
	$(call analysis_import_coldstart,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_COMPOSE),trident/artifacts,生产)

prod-stop:
	$(call analysis_down,$(ANALYSIS_PROD_ENV_FILE),$(ANALYSIS_PROD_PROJECT),$(ANALYSIS_PROD_COMPOSE))

prod-clean-db:
	cd $(ANALYSIS_DIR) && ./scripts/clean-db.sh prod

prod-logs:
	tail -f $(ANALYSIS_DIR)/trident/logs/worker.log

test-start-coldstart:
	$(call analysis_up,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_API_PORT),trident/logs-test,$(ANALYSIS_TEST_COMPOSE),$(ANALYSIS_COLDSTART_OVERRIDE),cold_start,测试,test-logs,--build)

test-start-inference:
	$(call analysis_up,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_API_PORT),trident/logs-test,$(ANALYSIS_TEST_COMPOSE),$(ANALYSIS_INFERENCE_OVERRIDE),inference,测试,test-logs,--build)

test-rebuild-coldstart:
	$(call analysis_up,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_API_PORT),trident/logs-test,$(ANALYSIS_TEST_COMPOSE),$(ANALYSIS_COLDSTART_OVERRIDE),cold_start,测试,test-logs,--build --force-recreate)

test-rebuild-inference:
	$(call analysis_up,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_API_PORT),trident/logs-test,$(ANALYSIS_TEST_COMPOSE),$(ANALYSIS_INFERENCE_OVERRIDE),inference,测试,test-logs,--build --force-recreate)

test-export-coldstart:
	$(call analysis_export_coldstart,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_COMPOSE),trident/artifacts-test,测试)

test-import-coldstart:
	$(call analysis_import_coldstart,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_COMPOSE),trident/artifacts-test,测试)

test-stop:
	$(call analysis_down,$(ANALYSIS_TEST_ENV_FILE),$(ANALYSIS_TEST_PROJECT),$(ANALYSIS_TEST_COMPOSE))

test-clean-db:
	cd $(ANALYSIS_DIR) && ./scripts/clean-db.sh test

test-logs:
	tail -f $(ANALYSIS_DIR)/trident/logs-test/worker.log

capture-start:
	cd capture && ./start.sh

capture-stop:
	cd capture && $(COMPOSE) -f compose.yaml down

capture-check:
	cd capture && ./check-redis-flow.sh

capture-logs:
	cd capture && $(COMPOSE) -f compose.yaml logs -f --tail=200 redis suricata-cic suricata-agent
