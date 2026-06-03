#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${RUNTIME_DIR:-${BUNDLE_DIR}/runtime}"
DEPLOY_ENV="${DEPLOY_ENV:-${BUNDLE_DIR}/deploy.env}"

load_deploy_env() {
  if [ -f "${DEPLOY_ENV}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${DEPLOY_ENV}"
    set +a
  fi
}

ensure_dirs() {
  mkdir -p \
    "${RUNTIME_DIR}/capture/suricata/config" \
    "${RUNTIME_DIR}/capture/suricata/logs" \
    "${RUNTIME_DIR}/analysis/trident/logs" \
    "${RUNTIME_DIR}/analysis/trident/artifacts" \
    "${RUNTIME_DIR}/analysis/docker" \
    "${RUNTIME_DIR}/ui"
}

write_capture_config() {
  cat > "${RUNTIME_DIR}/capture/suricata/config/capture-filter.json" <<'EOF'
{
  "enabled": true,
  "sourceIpRanges": [
    {
      "startIp": "0.0.0.0",
      "endIp": "255.255.255.255"
    }
  ],
  "destIpRanges": [
    {
      "startIp": "0.0.0.0",
      "endIp": "255.255.255.255"
    }
  ],
  "protocols": ["tcp", "udp", "icmp"],
  "extraBpf": "not arp and not broadcast and not multicast"
}
EOF
  cat > "${RUNTIME_DIR}/capture/suricata/config/filter.json" <<'EOF'
{
  "revision": 0,
  "enabled": true,
  "sourceIpRanges": [],
  "destIpRanges": [],
  "protocols": ["tcp", "udp", "icmp"]
}
EOF
}

write_trident_config() {
  cat > "${RUNTIME_DIR}/analysis/docker/trident.remote-redis.yaml" <<'EOF'
redis_url: redis://${CAPTURE_REDIS_HOST:-127.0.0.1}:${CAPTURE_REDIS_PORT:-16379}/0
queue_type: list
input_stream: suricata:cic_flow
consumer_group: trident-online
consumer_name: trident-01
consumer_mode: best_effort
best_effort_start_id: $
read_count: 512
block_ms: 1000
ack: true
list_maxlen: 100000

session_id: accuracy-mixed_attack_panel-aa2b640d82
window_size: 10000
feature_profile: compact_stats_no_env

clickhouse_dsn: http://default:trident@clickhouse:8123/default
postgres_dsn: postgresql://trident:trident@postgres:5432/trident

assignment_stream: trident:assignments
alert_stream: trident:alerts
metrics_stream: trident:metrics
redis_output_enabled: false

cold_start_exit_on_complete: true
inference_require_cold_start: true
cold_start_stable_windows: 40
cold_start_min_learners: 1
cold_start_min_windows: 2
cold_start_min_flows: 0

model_store_dir: /var/lib/trident/models
preprocessing_enabled: true
preprocessing_drop_all_zero: false

algorithm_backend: ae
cpu_only: true
seed: 42
init_epochs: 5
new_class_epochs: 4
increment_epochs: 1
min_class_samples: 300
max_train_per_class: 20000
max_increment_samples: 1000
increment_min_samples: 1000
tsieve_batch_size: 256
tsieve_lr: 0.001
evt_quantile: 0.97
evt_risk: 0.0015
fallback_quantile: 0.99
cluster_trigger_size: 120
new_learner_min_size: 500
dbscan_eps: 1.3
dbscan_min_samples: 10
max_unknown_buffer: 30000

pending_idle_ms: 60000
process_partial_window: true

benign_accept_scale: 0.34
benign_history_confidence_scale: 1.0
cluster_purity_gate_enabled: true
cluster_gate_max_benign_accept_rate: 0.35
cluster_gate_rejected_action: reinject_unknown
increment_drift_gate_enabled: true
increment_drift_min_score: 0.12
increment_drift_min_history_samples: 500
increment_route_gate_enabled: true
increment_route_apply_to_new_only: true
increment_route_min_samples: 1000
increment_route_min_own_margin: 0.02
increment_route_min_margin_gap: 0.03
increment_route_min_confident_ratio: 0.55
increment_iforest_guard_enabled: true
increment_iforest_guard_apply_to_new_only: true
increment_iforest_guard_min_samples: 1000
increment_iforest_guard_n_estimators: 200
increment_iforest_guard_train_max_samples: 5000
increment_iforest_guard_keep_quantile: 0.90
increment_sampling_mode: stratified_loss
increment_low_loss_quantile_keep: 1.0
history_sample_rate: 0.5
history_samples_per_update: 2000
max_history_samples_per_learner: 10000
history_time_decay_lambda: 0.0
small_learner_recluster_enabled: true
small_learner_sample_threshold: 1000
small_learner_recluster_count_trigger: 10
EOF
}

write_capture_compose() {
  cat > "${RUNTIME_DIR}/capture/compose.yaml" <<'EOF'
services:
  redis:
    image: redis:7-alpine
    container_name: streamtrident-redis
    command: ["redis-server", "--appendonly", "yes", "--bind", "0.0.0.0"]
    environment:
      TZ: Asia/Shanghai
    ports:
      - "${REDIS_HOST_PORT:-16379}:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20
    restart: unless-stopped

  redis-admin:
    image: streamtrident/redis-admin:local
    container_name: streamtrident-redis-admin
    depends_on:
      redis:
        condition: service_healthy
    command: ["python", "-m", "app.main", "ensure-group", "--config", "config/redis.yaml"]
    environment:
      TZ: Asia/Shanghai
    restart: "no"

  suricata-cic:
    image: streamtrident/suricata-cic:local
    container_name: streamtrident-suricata-cic
    network_mode: host
    cap_add:
      - NET_ADMIN
      - NET_RAW
      - SYS_NICE
    depends_on:
      redis:
        condition: service_healthy
    environment:
      TZ: Asia/Shanghai
      IFACE: "${SURICATA_IFACE:-eth0}"
      REDIS_HOST: "${SURICATA_REDIS_HOST:-127.0.0.1}"
      REDIS_PORT: "${REDIS_HOST_PORT:-16379}"
      REDIS_STREAM: "${SURICATA_REDIS_STREAM:-suricata:cic_flow}"
      REDIS_OUTPUT_MODE: "${SURICATA_REDIS_OUTPUT_MODE:-list}"
      REDIS_LIST_MAXLEN: "${SURICATA_REDIS_LIST_MAXLEN:-100000}"
      REDIS_STREAM_MAXLEN: "${SURICATA_REDIS_STREAM_MAXLEN:-1000000}"
      CIC_MODE: "${CIC_MODE:-cic-flowmeter}"
      CIC_FLOW_TIMEOUT_US: "${CIC_FLOW_TIMEOUT_US:-120000000}"
      CIC_ACTIVE_IDLE_THRESHOLD_US: "${CIC_ACTIVE_IDLE_THRESHOLD_US:-5000000}"
      SURICATA_CAPTURE_FILTER_CONFIG: /etc/suricata-cic/capture-filter.json
      SURICATA_TCP_NEW_TIMEOUT: "${SURICATA_TCP_NEW_TIMEOUT:-10}"
      SURICATA_TCP_EMERGENCY_NEW_TIMEOUT: "${SURICATA_TCP_EMERGENCY_NEW_TIMEOUT:-1}"
      SURICATA_RUNMODE: "${SURICATA_RUNMODE:-workers}"
      SURICATA_EXTRA_ARGS: "${SURICATA_EXTRA_ARGS:-}"
      SURICATA_FILTER_CONFIG: /etc/suricata-cic/filter.json
    volumes:
      - ./suricata/logs:/var/log/suricata
      - ./suricata/config:/etc/suricata-cic:ro
    restart: unless-stopped

  suricata-agent:
    image: streamtrident/suricata-agent:local
    container_name: streamtrident-suricata-agent
    environment:
      TZ: Asia/Shanghai
      SURICATA_FILTER_CONFIG_PATH: /etc/suricata-cic/filter.json
      SURICATA_CONTAINER: streamtrident-suricata-cic
      SURICATA_RESTART_TIMEOUT: "10"
      SURICATA_START_TIMEOUT: "${SURICATA_START_TIMEOUT:-15}"
      SURICATA_AGENT_MAX_BODY_BYTES: "${SURICATA_AGENT_MAX_BODY_BYTES:-262144}"
      SURICATA_AGENT_TOKEN: "${TRIDENT_SURICATA_AGENT_TOKEN:-}"
      SURICATA_IFACE: "${SURICATA_IFACE:-eth0}"
      SURICATA_REDIS_HOST: redis
      SURICATA_REDIS_PORT: "6379"
      SURICATA_REDIS_KEY: "${SURICATA_REDIS_STREAM:-suricata:cic_flow}"
      DOCKER_SOCKET: /var/run/docker.sock
    volumes:
      - ./suricata/config:/etc/suricata-cic
      - /var/run/docker.sock:/var/run/docker.sock
    ports:
      - "${SURICATA_AGENT_HOST_PORT:-19100}:19100"
    restart: unless-stopped

volumes:
  redis-data:
EOF
}

write_analysis_compose() {
  cat > "${RUNTIME_DIR}/analysis/compose.yaml" <<'EOF'
services:
  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    container_name: streamtrident-clickhouse
    ports:
      - "${CLICKHOUSE_HTTP_HOST_PORT:-18123}:8123"
      - "${CLICKHOUSE_NATIVE_HOST_PORT:-19000}:9000"
    environment:
      TZ: Asia/Shanghai
      CLICKHOUSE_DB: default
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: trident
    volumes:
      - clickhouse-data:/var/lib/clickhouse
    healthcheck:
      test: ["CMD", "clickhouse-client", "--query", "SELECT 1"]
      interval: 5s
      timeout: 3s
      retries: 30
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: streamtrident-postgres
    ports:
      - "${POSTGRES_HOST_PORT:-15432}:5432"
    environment:
      TZ: Asia/Shanghai
      POSTGRES_DB: trident
      POSTGRES_USER: trident
      POSTGRES_PASSWORD: trident
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U trident -d trident"]
      interval: 5s
      timeout: 3s
      retries: 30
    restart: unless-stopped

  trident-migrate:
    image: streamtrident/trident:cpu-protected
    container_name: streamtrident-migrate
    depends_on:
      clickhouse:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      TZ: Asia/Shanghai
      TRIDENT_LOG_DIR: /var/log/trident
      TRIDENT_LOG_FILE: migrate.log
    volumes:
      - ./docker/trident.remote-redis.yaml:/app/config/trident.yaml:ro
      - ./trident/logs:/var/log/trident
    command: ["python", "-m", "app.migrate", "--config", "config/trident.yaml"]
    restart: "no"

  trident-worker:
    image: streamtrident/trident:cpu-protected
    container_name: streamtrident-worker
    depends_on:
      clickhouse:
        condition: service_healthy
      postgres:
        condition: service_healthy
      trident-migrate:
        condition: service_completed_successfully
    environment:
      TZ: Asia/Shanghai
      TRIDENT_LOG_DIR: /var/log/trident
      TRIDENT_LOG_FILE: worker.log
      CAPTURE_REDIS_HOST: "${CAPTURE_REDIS_HOST:-host.docker.internal}"
      CAPTURE_REDIS_PORT: "${CAPTURE_REDIS_PORT:-16379}"
      NVIDIA_VISIBLE_DEVICES: ""
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - trident-models:/var/lib/trident/models
      - ./docker/trident.remote-redis.yaml:/app/config/trident.yaml:ro
      - ./trident/logs:/var/log/trident
    command: ["python", "-m", "app.worker", "--config", "config/trident.yaml", "--mode", "${TRIDENT_WORKER_MODE:-cold_start}"]
    restart: unless-stopped

  trident-api:
    image: streamtrident/trident:cpu-protected
    container_name: streamtrident-api
    depends_on:
      clickhouse:
        condition: service_healthy
      postgres:
        condition: service_healthy
      trident-migrate:
        condition: service_completed_successfully
    environment:
      TZ: Asia/Shanghai
      TRIDENT_LOG_DIR: /var/log/trident
      TRIDENT_LOG_FILE: api.log
      TRIDENT_SURICATA_AGENT_URLS: "${TRIDENT_SURICATA_AGENT_URLS:-http://host.docker.internal:19100}"
      TRIDENT_SURICATA_AGENT_TOKEN: "${TRIDENT_SURICATA_AGENT_TOKEN:-}"
      CAPTURE_REDIS_HOST: "${CAPTURE_REDIS_HOST:-host.docker.internal}"
      CAPTURE_REDIS_PORT: "${CAPTURE_REDIS_PORT:-16379}"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - trident-models:/var/lib/trident/models
      - ./docker/trident.remote-redis.yaml:/app/config/trident.yaml:ro
      - ./trident/logs:/var/log/trident
    command: ["python", "-m", "app.api", "--config", "config/trident.yaml", "--host", "0.0.0.0", "--port", "8090"]
    ports:
      - "${TRIDENT_API_HOST_PORT:-8090}:8090"
    restart: unless-stopped

  trident-tools:
    image: streamtrident/trident:cpu-protected
    container_name: streamtrident-tools
    depends_on:
      clickhouse:
        condition: service_healthy
      postgres:
        condition: service_healthy
      trident-migrate:
        condition: service_completed_successfully
    environment:
      TZ: Asia/Shanghai
      TRIDENT_LOG_DIR: /var/log/trident
      TRIDENT_LOG_FILE: coldstart-artifact.log
    volumes:
      - trident-models:/var/lib/trident/models
      - ./docker/trident.remote-redis.yaml:/app/config/trident.yaml:ro
      - ./trident/logs:/var/log/trident
      - ./trident/artifacts:/var/lib/trident/artifacts
    command: ["python", "-m", "app.coldstart_artifact", "--help"]
    restart: "no"

volumes:
  clickhouse-data:
  postgres-data:
  trident-models:
EOF
}

write_ui_compose() {
  cat > "${RUNTIME_DIR}/ui/compose.yaml" <<'EOF'
services:
  v3-ui-2:
    image: v3-ui-2:latest
    container_name: v3-ui-2
    ports:
      - "${UI_HOST_PORT:-8088}:80"
    environment:
      API_AUTH_UPSTREAM: ${API_AUTH_UPSTREAM:-http://host.docker.internal:8090}
      API_TRIDENT_UPSTREAM: ${API_TRIDENT_UPSTREAM:-http://host.docker.internal:8090}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
EOF
}

prepare_runtime() {
  load_deploy_env
  ensure_dirs
  write_capture_config
  write_trident_config
  write_capture_compose
  write_analysis_compose
  write_ui_compose
}
