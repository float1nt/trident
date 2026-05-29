# StreamTrident Services

实时流处理工程骨架。生产部署按采集侧和分析侧隔离：

- `capture/`：采集侧，包含 Redis、修改版 Suricata、Suricata agent
- `analysis/`：分析侧，包含 Trident、PostgreSQL、ClickHouse

父目录保留一份 `compose.yaml`，只用于本地全量联调。

## Service Layout

```text
streamtrident_services/
├── capture/
│   ├── compose.yaml
│   ├── .env.example
│   ├── start.sh
│   ├── redis/
│   ├── suricata/
│   └── suricata-agent/
├── analysis/
│   ├── compose.yaml
│   ├── .env.example
│   ├── scripts/
│   └── trident/
└── compose.yaml
```

## Split Deployment

当前推荐拓扑（采集 `172.16.88.12` / `ens35`，分析在本机 test 栈）见 [docs/SPLIT_DEPLOY.md](docs/SPLIT_DEPLOY.md)。

On the capture host (`172.16.88.12`):

```bash
cd streamtrident_services/capture
cp .env.split .env
./start.sh
```

On the analysis host (local):

```bash
cd streamtrident_services
make test-start-coldstart   # build baseline from benign traffic
make test-start-inference   # switch worker to inference after cold start completes
```

For other hosts, set these in `analysis/.env` or `analysis/.env.test`:

- `CAPTURE_REDIS_HOST`: capture host IP (e.g. `172.16.88.12`)
- `TRIDENT_SURICATA_AGENT_URLS`: capture host agent URL (e.g. `http://172.16.88.12:19100`)

## Local Run

```bash
cd streamtrident_services
make capture-start
make test-start-coldstart
make test-start-inference
```

This starts capture services and the test analysis stack on one machine for development.

Host ports default to non-standard values to avoid conflicts with services already installed on the host:

- Redis: `127.0.0.1:16379` -> container `6379`
- ClickHouse HTTP: `127.0.0.1:18123` -> container `8123`
- ClickHouse native: `127.0.0.1:19000` -> container `9000`
- PostgreSQL: `127.0.0.1:15432` -> container `5432`
- Trident API: `127.0.0.1:8090` -> container `8090`

Override them in `capture/.env`, `analysis/.env`, or `analysis/.env.test` when needed.

Suricata uses host networking and captures from `SURICATA_IFACE`, defaulting to `eth0`. Set it to the actual host NIC before starting capture.

For production-style local testing, use `make prod-start-coldstart` and `make prod-start-inference` from `streamtrident_services`.

The capture service writes CIC flow records to Redis list `suricata:cic_flow` by default. Trident worker consumes that list with pop semantics, so records are removed from Redis as soon as Trident takes them.

Useful Suricata settings:

- `SURICATA_IFACE`: host interface to capture from, for example `eth0`, `ens33`, `enp0s3`
- `SURICATA_REDIS_STREAM`: Redis queue key, default `suricata:cic_flow`
- `SURICATA_REDIS_OUTPUT_MODE`: Redis output mode, default `list`
- `SURICATA_REDIS_STREAM_MAXLEN`: Redis stream max length when `SURICATA_REDIS_OUTPUT_MODE=stream`, default `1000000`
- `CIC_FLOW_TIMEOUT_US`: flow timeout in microseconds, default `120000000`
- `CIC_ACTIVE_IDLE_THRESHOLD_US`: CIC active/idle threshold in microseconds, default `5000000`

After startup, verify that flow data is being written:

```bash
make capture-logs
make capture-check
```

Manual checks:

```bash
redis-cli -p 16379 LLEN suricata:cic_flow
redis-cli -p 16379 LRANGE suricata:cic_flow -1 -1
```

## Local Commands

```bash
cd streamtrident_services/capture/redis
python -m app.main ensure-group --config config/redis.yaml

cd streamtrident_services/analysis/trident
python -m app.migrate --config config/trident.yaml
python -m app.worker --config config/trident.yaml --once
python -m app.api --config config/trident.yaml --host 127.0.0.1 --port 8090
```

## Logs

Each service writes its own logs to a dedicated host directory:

- `capture/suricata/` -> `capture/suricata/logs/`
- `analysis/trident/` -> `analysis/trident/logs/`

Trident app logs are JSON-line files and are rotated by the application itself.
Suricata keeps its native log files under `suricata/logs/`.

## Current Boundary

- 不引用 `trident_demo`
- 不做前端
- 不把 Suricata、Redis、Trident 放进同一个 Python 应用里
