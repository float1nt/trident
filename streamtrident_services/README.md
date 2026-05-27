# StreamTrident Services

三服务实时流处理工程骨架。这里不再使用单体 `backend/app/modules` 结构，而是把三个服务放在同一父目录下的三个顶层目录中：

- `suricata/`：采集侧，从网卡抓包，由修改版 Suricata 输出 CIC 风格 flow 到 Redis Stream
- `redis/`：Redis 服务与 Stream 管理
- `trident/`：Trident 在线算法、持久化、worker 和 API

父目录提供一份 `compose.yaml`，用于本地部署和联调 Suricata、Redis、ClickHouse、PostgreSQL、Trident worker/API。

## Service Layout

```text
streamtrident_services/
├── suricata/
│   ├── docker/
│   ├── runtime/
│   ├── logs/
│   ├── Dockerfile
│   └── README.md
├── redis/
│   ├── app/
│   ├── config/
│   ├── Dockerfile
│   ├── compose.yaml
│   └── requirements.txt
├── trident/
    ├── app/
    ├── config/
    ├── Dockerfile
    ├── migrations/
    └── requirements.txt
├── docker/
│   ├── redis.yaml
│   └── trident.yaml
└── compose.yaml
```

## Docker Compose

```bash
cd streamtrident_services
docker compose up -d
```

This starts:

- Redis
- Suricata CIC capture service
- ClickHouse
- PostgreSQL
- one-shot Redis group initialization
- one-shot database migration
- Trident worker
- Trident API on `http://127.0.0.1:8090`

Host ports default to non-standard values to avoid conflicts with services already installed on the host:

- Redis: `127.0.0.1:16379` -> container `6379`
- ClickHouse HTTP: `127.0.0.1:18123` -> container `8123`
- ClickHouse native: `127.0.0.1:19000` -> container `9000`
- PostgreSQL: `127.0.0.1:15432` -> container `5432`
- Trident API: `127.0.0.1:8090` -> container `8090`

Override them when needed:

```bash
REDIS_HOST_PORT=6379 POSTGRES_HOST_PORT=5432 docker compose up -d
```

Suricata uses host networking and captures from `SURICATA_IFACE`, defaulting to `eth0`. Set it to the actual host NIC when starting:

```bash
cd streamtrident_services
SURICATA_IFACE=ens33 docker compose up -d --build suricata-cic trident-worker trident-api
```

The capture service writes CIC flow records to Redis stream `suricata:cic_flow` by default. Trident worker consumes that stream and performs database persistence and algorithm processing.

Useful Suricata settings:

- `SURICATA_IFACE`: host interface to capture from, for example `eth0`, `ens33`, `enp0s3`
- `SURICATA_REDIS_STREAM`: output stream name, default `suricata:cic_flow`
- `SURICATA_REDIS_STREAM_MAXLEN`: Redis stream max length, default `1000000`
- `CIC_FLOW_TIMEOUT_US`: flow timeout in microseconds, default `120000000`
- `CIC_ACTIVE_IDLE_THRESHOLD_US`: CIC active/idle threshold in microseconds, default `5000000`

After startup, verify that flow data is being written:

```bash
docker compose logs -f suricata-cic
redis-cli -p 16379 XLEN suricata:cic_flow
redis-cli -p 16379 XREVRANGE suricata:cic_flow + - COUNT 1
```

## Local Commands

```bash
cd streamtrident_services/redis
python -m app.main ensure-group --config config/redis.yaml

cd streamtrident_services/trident
python -m app.migrate --config config/trident.yaml
python -m app.worker --config config/trident.yaml --once
python -m app.api --config config/trident.yaml --host 127.0.0.1 --port 8090
```

## Logs

Each service writes its own logs to a dedicated host directory:

- `suricata/` -> `suricata/logs/`
- `trident/` -> `trident/logs/`

Trident app logs are JSON-line files and are rotated by the application itself.
Suricata keeps its native log files under `suricata/logs/`.

## Current Boundary

- 不引用 `trident_demo`
- 不做前端
- 不把 Suricata、Redis、Trident 放进同一个 Python 应用里
