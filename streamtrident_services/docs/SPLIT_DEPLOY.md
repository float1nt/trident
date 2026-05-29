# 采集侧 / 分析侧分离部署

本指南对应当前拓扑：

| 角色 | 主机 | 网卡 / 说明 |
|------|------|-------------|
| 采集侧 | `172.16.88.12` | `ens35` 接镜像口 |
| 分析侧 | 本机 | `analysis/compose.test.yaml` + `.env.test` |

## 1. 采集侧（172.16.88.12）

在采集机上进入工程目录：

```bash
cd streamtrident_services/capture
cp .env.split .env
# 确认 ens35 已配置 172.16.88.12，且能收到镜像流量
ip -br addr show ens35
./start.sh
```

或直接使用 split 配置：

```bash
ENV_FILE=.env.split ./start.sh
```

启动后对外服务（默认监听 `0.0.0.0`）：

| 服务 | 端口 | 用途 |
|------|------|------|
| Redis | `16379` | Trident worker 消费 `suricata:cic_flow` |
| suricata-agent | `19100` | API 下发采集过滤规则 |

**防火墙**：在采集机上放行分析机访问上述端口，例如（将 `ANALYSIS_IP` 换成分析机地址）：

```bash
sudo ufw allow from ANALYSIS_IP to any port 16379 proto tcp
sudo ufw allow from ANALYSIS_IP to any port 19100 proto tcp
```

验证采集是否正常：

```bash
make capture-logs
make capture-check
```

脚本会在约 20 秒内轮询队列长度，并抽样校验最新一条 flow JSON（不 pop 数据）。若分析侧 worker 正在消费，队列可能经常为 0，脚本会以观测窗口内的峰值长度为准。

从分析机测试连通：

```bash
redis-cli -h 172.16.88.12 -p 16379 PING
curl -sS http://172.16.88.12:19100/agent/v1/health
```

## 2. 分析侧（本机）

```bash
cd streamtrident_services
# analysis/.env.test 已指向采集机 172.16.88.12
make test-start-coldstart
```

冷启动完成后切到推理：

```bash
make test-start-inference
```

分析栈端口（与生产分析栈错开，避免冲突）：

| 服务 | 端口 |
|------|------|
| trident-api | `9090` |
| PostgreSQL | `25432` |
| ClickHouse HTTP | `28123` |
| ClickHouse native | `29000` |

关键环境变量（`analysis/.env.test`）：

```bash
CAPTURE_REDIS_HOST=172.16.88.12
CAPTURE_REDIS_PORT=16379
TRIDENT_SURICATA_AGENT_URLS=http://172.16.88.12:19100
```

停止分析栈：

```bash
make test-stop
```

## 3. 端到端检查

```bash
# 分析机：API 健康
curl -sS http://127.0.0.1:9090/api/v1/health

# 分析机：worker 是否在消费（日志中应有 redis 读取）
make test-logs

# 采集机：队列是否在增长/被消费
redis-cli -h 172.16.88.12 -p 16379 LLEN suricata:cic_flow
```

## 4. 修改采集机 IP 或网卡

- 采集机：编辑 `capture/.env`（或 `.env.split`）中的 `SURICATA_IFACE`、`REDIS_HOST_PORT` 等。
- 分析机：编辑 `analysis/.env.test` 中的 `CAPTURE_REDIS_HOST`、`TRIDENT_SURICATA_AGENT_URLS`。

两处端口与 token 需保持一致。
