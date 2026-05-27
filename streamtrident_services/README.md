# StreamTrident Services

三服务实时流处理工程骨架。这里不再使用单体 `backend/app/modules` 结构，而是把三个服务放在同一父目录下的三个顶层目录中：

- `suricata/`：采集侧，归一化 flow JSON 并写入 Redis Stream
- `redis/`：Redis 服务与 Stream 管理
- `trident/`：Trident 在线算法、持久化、worker 和 API

三者各自有独立的 `app/`、`config/`、`requirements.txt`、`Dockerfile` 和启动命令。父目录提供一份 `compose.yaml`，用于本地部署和联调 Redis、ClickHouse、PostgreSQL、Trident worker/API。

## Service Layout

```text
streamtrident_services/
├── suricata/
│   ├── app/
│   ├── config/
│   ├── Dockerfile
│   └── requirements.txt
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
│   ├── suricata.yaml
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

To run the stdin publisher tool profile:

```bash
cd streamtrident_services
docker compose --profile tools run --rm suricata-publisher
```

`suricata-publisher` reads one JSON object per line from stdin and writes normalized fields to `suricata:cic_flow`.

## Local Commands

```bash
cd streamtrident_services/redis
python -m app.main ensure-group --config config/redis.yaml

cd streamtrident_services/trident
python -m app.migrate --config config/trident.yaml
python -m app.worker --config config/trident.yaml --once
python -m app.api --config config/trident.yaml --host 127.0.0.1 --port 8090
```

## Current Boundary

- 不引用 `trident_demo`
- 不做前端
- 不把 Suricata、Redis、Trident 放进同一个 Python 应用里
