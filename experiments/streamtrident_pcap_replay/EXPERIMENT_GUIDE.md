# PCAP 重放注入实验指南

通过 **tcpreplay → Suricata 实时抓包 → Redis Stream → Trident Worker** 做端到端（E2E）实验，与 CSV 直注 Redis 的准确率脚本互补。

## 实验目标

| 阶段 | 数据源 | 目的 |
|---|---|---|
| **Warmup（冷启动）** | CICIDS2017 `Monday-WorkingHours.pcap` | 重放直至 Trident 处理 **≥50,000** 条 flow，建立 baseline learner（`0000\|UNLABELED`） |
| **Eval（推理）** | CICIDS2017 `Tuesday-WorkingHours.pcap` | 整包重放一次，观察在线聚类、风险 learner、unknown 率、UI 总览 |

Tuesday 含 FTP-Patator、SSH-Patator 等攻击流量，适合验证「Monday 良性冷启动 → Tuesday 混合/攻击推理」的真实链路。

## 数据流架构

```text
Monday/Tuesday PCAP
        │
        ▼  tcpreplay -i <IFACE>
   主机网卡 (eno1)
        │
        ▼  Suricata live capture (host network)
 streamtrident-suricata-cic
        │  cic-flowmeter EVE → Redis XADD
        ▼
 Redis Stream  suricata:cic_flow  (16379)
        │
        ▼  实验本地 worker（独立 session_id）
 Trident OnlineEngine
        │
        ├── ClickHouse  ch_flow
        └── PostgreSQL  pg_learner
```

与 CSV 注入的区别：

| 项目 | CSV 注入 (`run_accuracy_eval.py`) | PCAP 重放（本文） |
|---|---|---|
| Suricata | 不需要 | **必须** |
| 特征来源 | CSV 预提取 `features_json` | Suricata cic-flowmeter 实时生成 |
| Ground truth 标签 | 有（flow_uid 对齐） | **无**（需另做离线对齐） |
| 验证重点 | 聚合准确率 | **全链路 E2E + 在线行为** |

## 前置条件

### 1. PCAP 文件

原始包（~10 GB）：

```text
/home/sr/HyperVision-main/test_file/Monday-WorkingHours.pcap
/home/sr/HyperVision-main/test_file/Tuesday-WorkingHours.pcap
```

**实验前须做 MTU1500 截断**（避免 tcpreplay `Message too long`）：

```bash
python3 experiments/streamtrident_pcap_replay/run_pcap_replay_eval.py --prepare-pcaps
```

输出：

```text
experiments/streamtrident_pcap_replay/pcaps/Monday-WorkingHours.mtu1500.pcap
experiments/streamtrident_pcap_replay/pcaps/Tuesday-WorkingHours.mtu1500.pcap
```

使用 `tcprewrite --mtu=1500 --mtu-trunc --fixcsum` 生成；主实验脚本默认自动准备（可用 `--skip-prepare-pcaps` 跳过）。

Suricata **flow-timeout 保持 compose 默认 120s**，不在实验中修改。

### 2. 工具

- `tcpreplay`（本机 `/usr/bin/tcpreplay`）
- Docker Compose：`streamtrident_services`

### 3. 网卡

Suricata 与 tcpreplay **必须共用同一 host 网卡**。本机推荐：

```text
eno1   UP
```

对应 compose 环境变量：`SURICATA_IFACE=eno1`

### 4. 端口

| 服务 | 端口 |
|---|---|
| Redis | 16379 |
| ClickHouse HTTP | 18123 |
| PostgreSQL | 15432 |
| Trident API（可选 UI） | 8090 |

## 推荐执行步骤

### 1. 停止 Docker worker（避免与实验 worker 抢消费）

```bash
cd streamtrident_services
docker compose stop trident-worker
```

### 2. 启动 capture + 存储依赖

```bash
SURICATA_IFACE=eno1 docker compose up -d redis clickhouse postgres suricata-cic suricata-agent
```

确认 Suricata 未重启循环：

```bash
docker ps --filter name=streamtrident-suricata-cic
docker logs streamtrident-suricata-cic --tail 30
```

### 3. 运行实验脚本

```bash
python3 experiments/streamtrident_pcap_replay/run_pcap_replay_eval.py \
  --iface eno1 \
  --warmup-flows 50000 \
  --warmup-mbps 500 \
  --eval-mbps 500 \
  --settle-seconds 45 \
  --timeout 7200 \
  --sync-docker-config
```

脚本会先 `tcprewrite` 生成 mtu1500 PCAP（若已存在且较新则跳过），再开始重放。

脚本会自动：

1. 记录 Redis `before_id`，启动**独立 session** 的本地 worker
2. **Monday**：`tcpreplay` 循环重放，ClickHouse 处理数 ≥50k 后停止
3. 等待 warmup 处理完成
4. **Tuesday**：整包重放 1 次
5. 空闲稳定后输出 `summary.json`（learner 数、unknown 率等）
6. `--sync-docker-config` 时把 `session_id` 写入 `analysis/docker/trident.yaml` 供 UI 查看

### 4. 恢复 Docker worker（可选）

```bash
docker compose up -d trident-worker trident-api
```

## 脚本参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--monday-pcap` | HyperVision Monday 路径 | Warmup PCAP |
| `--tuesday-pcap` | HyperVision Tuesday 路径 | Eval PCAP |
| `--iface` | `eno1` | tcpreplay / Suricata 共用网卡 |
| `--warmup-flows` | `50000` | Monday 冷启动目标 flow 数 |
| `--warmup-mbps` | `500` | Monday 重放速率 |
| `--eval-mbps` | `500` | Tuesday 重放速率 |
| `--settle-seconds` | `45` | Tuesday 重放后等待 Suricata/Worker 消化 |
| `--timeout` | `7200` | 各阶段超时（秒） |
| `--skip-deps` | off | 跳过 compose up / stop worker |
| `--sync-docker-config` | off | 写 session 到 docker trident.yaml |

## 输出目录

```text
outputs/streamtrident_pcap_replay/<run_id>/
├── manifest.json
├── summary.json
└── pcap_monday_tuesday/
    ├── trident_eval_config.yaml
    ├── worker.log
    ├── warmup_replay.log
    ├── eval_replay.log
    └── summary.json
```

`summary.json` 关键字段：

| 字段 | 含义 |
|---|---|
| `session_id` | 实验命名空间，如 `pcap-replay-a1b2c3d4e5` |
| `warmup_stats.processed` | Monday 后累计处理 flow |
| `eval_flows` | Tuesday 新增 flow（总 processed − warmup） |
| `unknown_rate` | unknown / 总 processed |
| `learner_rows` | 各 learner 流量与 risk_band |

## 与 UI 联调

实验完成后若已 `--sync-docker-config`：

```bash
cd streamtrident_services
docker compose up -d --force-recreate trident-api
```

浏览器打开 `http://127.0.0.1:5175/`，总览/风险页读取该 session 数据。

**注意**：PCAP 路径下 flow 的 `event_time` 来自 Suricata/capture 时间或包内时间戳，与 CSV 实验不同；若总览时间窗过滤导致趋势图为空，请选「近 7 天/近 30 天」。

## 常见问题

### Suricata 容器反复 Restart

- 检查 `SURICATA_IFACE` 是否存在：`ip link show eno1`
- 查看 `docker logs streamtrident-suricata-cic`

### Redis 有数据但 Worker 不消费

- 确认已 `stop trident-worker`，仅实验本地 worker 在跑
- 查看 `pcap_monday_tuesday/worker.log`

### Monday 重放很久不到 5 万 flow

- 确认已使用 **mtu1500** PCAP（`--prepare-pcaps`），`warmup_replay.log` 无大量 `Message too long`
- 提高 `--warmup-mbps`
- 检查 Suricata 是否写入 Redis：`docker exec streamtrident-redis redis-cli XLEN suricata:cic_flow`
- **120s flow-timeout** 主要影响 PCAP 收尾阶段；持续 loop 重放时中间流量不应受此严重拖累

### 需要标签准确率

PCAP E2E **不自带 ground truth**。若要 strict/coarse 准确率，请继续用：

```bash
experiments/streamtrident_accuracy_eval/run_accuracy_eval.py
```

或在 PCAP 实验后，用 Tuesday CSV 做离线 join（flow 五元组 + 时间窗对齐，未在本脚本实现）。

## 与现有 harness 的关系

| 组件 | 路径 | 用途 |
|---|---|---|
| 本实验 | `experiments/streamtrident_pcap_replay/` | Monday/Tuesday 冷启动 + 推理，对接 `streamtrident_services` |
| Demo stress | `trident_demo/stress/controller.py` | 通用 E2E 压测 / 性能 benchmark |
| CSV 准确率 | `experiments/streamtrident_accuracy_eval/` | 有标签聚合准确率 |

## 实验记录

| run_id | session_id | warmup flows | eval flows | learners | unknown_rate | 备注 |
|---|---|---:|---:|---:|---:|---|
| `20260528_152051_4c9c01aa` | `pcap-replay-15990c8f5a` | 160238（目标 5 万，Redis 积压继续消费） | 460000 | 1 | 1.62% | MTU1500 PCAP；500 Mbps；Suricata 120s timeout 未改；Tuesday 重放 124s |
