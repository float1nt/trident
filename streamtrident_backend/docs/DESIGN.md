# StreamTrident Backend — 设计方案

独立实时流处理后端。基于三服务流式架构（Suricata → Redis → Trident）与双核心表数据模型（ClickHouse `ch_flow` + PostgreSQL `pg_learner`）重新设计，**不依赖、不引用**任何既有 demo 代码或静态批处理链路。

---

## 1. 设计目标

| 目标 | 说明 |
|------|------|
| 纯实时 | 只处理 Redis Stream 上的连续 flow 事件，无 CSV / PCAP / 离线回放 / 静态文件导入 |
| 无标签 | 不存储 ground truth、不计算分类准确率、不做有监督评估 |
| 三模块独立 | Suricata、Redis、Trident 各自独立部署、独立生命周期，通过 Stream 契约解耦 |
| 四层后端 | 每个可对外提供 HTTP 的模块统一采用 `routes → controllers → services → models` |
| 双表中心 | 运行时写入以 `ch_flow`（流事实）和 `pg_learner`（学习器当前态）为核心 |
| 历史可追溯 | `pg_learner_snapshot` 只在学习器状态更新时追加版本，支持历史解释查询 |

---

## 2. 总体架构

```text
                    ┌─────────────────────────────────────┐
                    │         Mirror / SPAN Traffic        │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │   Suricata Module (独立进程/服务)     │
                    │   捕获 → CIC flow 特征 → XADD        │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │   Redis Module (独立基础设施)         │
                    │   Stream 缓冲 / Consumer Group       │
                    │   suricata:cic_flow                  │
                    │   trident:assignments (可选输出)      │
                    │   trident:metrics (可选输出)          │
                    └──────────────────┬──────────────────┘
                                       │
          ┌────────────────────────────┐
          │                            │
┌─────────▼─────────┐      ┌───────────▼──────────┐
│ Trident Worker    │      │ Trident API          │
│ 消费→推理→写库     │      │ 4 个读接口 + health   │
└─────────┬─────────┘      └───────────┬──────────┘
          │                            │
          └──────────────┬─────────────┘
                         │
              ┌──────────▼──────────┐
              │ ClickHouse ch_flow  │
              │ PostgreSQL pg_learner│  ← 当前态（覆盖更新）
              │ pg_learner_snapshot  │  ← 历史快照（只追加）
              └─────────────────────┘
```

**部署单元（3 个独立服务 + 2 个数据库）：**

| 服务 | 职责 | 是否暴露 HTTP |
|------|------|---------------|
| `suricata-service` | 流量采集与 flow 特征产出，写入 Redis Stream | 可选（健康/状态） |
| `redis-service` | Redis 实例本身（运维部署），非应用代码 | 否（仅 Redis 协议） |
| `trident-service` | 消费 Stream、在线推理、Live flush、查询 API | 是 |

Redis 作为中间件独立运维；应用侧通过 **redis-bridge 模块** 封装 Stream 读写与监控，不内嵌 Redis 进程。

---

## 3. 项目目录结构

```text
streamtrident_backend/
├── docs/
│   └── DESIGN.md                 # 本文档
├── config/
│   ├── suricata.yaml             # Suricata 模块配置
│   ├── redis_bridge.yaml         # Stream key、consumer group、URL
│   └── trident.yaml              # 窗口、session、DB、flush 周期
├── app/
│   ├── main.py                   # Trident API 入口（FastAPI）
│   ├── worker.py                 # Trident 后台 Worker 入口
│   ├── common/
│   │   ├── config.py             # 配置加载
│   │   ├── logging.py
│   │   ├── exceptions.py
│   │   └── db/
│   │       ├── clickhouse_pool.py
│   │       └── postgres_pool.py
│   └── modules/
│       ├── suricata/             # Suricata 集成模块
│       │   ├── routes/
│       │   ├── controllers/
│       │   ├── services/
│       │   └── models/
│       ├── redis_bridge/         # Redis Stream 桥接模块
│       │   ├── routes/
│       │   ├── controllers/
│       │   ├── services/
│       │   └── models/
│       └── trident/              # Trident 在线处理 + 查询模块
│           ├── routes/
│           ├── controllers/
│           ├── services/
│           └── models/
└── migrations/
    ├── clickhouse/
    │   └── 001_ch_flow.sql
    └── postgres/
        ├── 001_pg_learner.sql
        └── 002_pg_learner_snapshot.sql
```

**刻意不包含：**

- `scripts/`、`tools/`、`stress/`、`benchmark/`
- `frontend/`、`visualize/`、任何 UI 静态资源
- `data/`、`outputs/`、CSV/PCAP 样例目录
- 批处理 pipeline、实验 runner、decision tree 导出

---

## 4. 四层架构约定

每一层职责固定，模块间禁止跨层直调（例如 routes 不得直接访问 models）。

```text
HTTP Request
    │
    ▼
routes/          路由注册、路径参数、请求体校验（Pydantic schema）
    │
    ▼
controllers/     编排单次请求：解析参数 → 调 service → 组装响应 / 错误码
    │
    ▼
services/        业务逻辑：窗口推理、Live flush、Stream 消费、指标/规则计算
    │
    ▼
models/          表结构映射、CRUD、UPSERT、批量 INSERT，不含业务判断
```

| 层 | 允许 | 禁止 |
|----|------|------|
| routes | 声明 URL、依赖注入、DTO 校验 | 数据库访问、业务分支 |
| controllers | 调用多个 service、事务边界声明 | SQL、Redis 原语、算法细节 |
| services | 算法、聚合、跨 model 协调 | 直接拼 HTTP 响应 |
| models | SQL/ORM、字段映射、索引感知查询 | 窗口逻辑、规则权重 |

---

## 5. 模块一：Suricata

### 5.1 定位

独立部署的流量采集侧。负责从镜像口持续读取网络流量，形成 **单条 flow = 一条 Redis Stream 消息**，不在本模块做 Trident 推理。

### 5.2 运行时形态

```text
suricata-service (systemd / container)
  ├── Suricata 引擎进程（eve-log / plugin 输出 CIC 风格字段）
  └── streamtrident suricata-writer（本仓库子进程）
        └── XADD suricata:cic_flow *
```

`suricata-writer` 是轻量常驻进程，只做：**读 Suricata 输出 → 字段归一化 → XADD**。

### 5.3 目录与四层

```text
modules/suricata/
├── routes/
│   └── health_routes.py          # GET /suricata/health
├── controllers/
│   └── health_controller.py
├── services/
│   ├── capture_supervisor.py     # 进程存活、重启策略
│   ├── flow_normalizer.py        # CIC 字段别名 → 标准字段
│   └── stream_publisher.py       # 调用 redis_bridge 写入
└── models/
    └── suricata_runtime_state.py # 内存态：最后写入时间、累计条数（可选落 pg_session）
```

### 5.4 Stream 消息契约

写入 `suricata:cic_flow` 的每条消息：

```json
{
  "event_type": "cic_flow",
  "event_time": "2026-05-26T10:15:23.123Z",
  "src_ip": "192.168.1.10",
  "dst_ip": "8.8.8.8",
  "src_port": 51544,
  "dst_port": 443,
  "protocol": 6,
  "source_flow_id": "123456789",
  "features": {
    "Flow Duration": 1205,
    "Total Fwd Packet": 8,
    "Total Bwd packets": 5
  }
}
```

Suricata 模块**不暴露 HTTP**。健康状态通过进程监控或日志采集，必要时由 Trident `/health` 间接反映上游 Stream 是否有新消息。

---

## 6. 模块二：Redis Bridge

### 6.1 定位

**不运行 Redis 服务器**。封装应用侧对 Redis Stream 的读写、Consumer Group 管理、积压监控。Suricata 与 Trident 均通过本模块访问 Redis，避免散落 `XREADGROUP` 调用。

### 6.2 Stream 规划

| Stream Key | 方向 | 用途 |
|------------|------|------|
| `suricata:cic_flow` | Suricata → Trident | 输入 flow 特征 |
| `trident:assignments` | Trident → 下游 | 分配结果（可选） |
| `trident:metrics` | Trident → 监控 | 窗口级运行指标（可选） |

Consumer Group 固定名：`trident-online`；Consumer 名：`{hostname}-{pid}`。

### 6.3 目录与四层

```text
modules/redis_bridge/
├── routes/
│   └── stream_routes.py          # GET /redis/streams/...
├── controllers/
│   └── stream_controller.py
├── services/
│   ├── stream_reader.py          # XREADGROUP、pending 恢复
│   ├── stream_writer.py          # XADD assignments/metrics
│   ├── consumer_group_manager.py # XGROUP CREATE、XACK、XAUTOCLAIM
│   └── stream_health.py          # XLEN、XPENDING、lag 估算
└── models/
    └── redis_client.py           # 连接池、重连、超时
```

### 6.4 核心 Service 接口

```python
# 仅供说明，非实现代码

class StreamReaderService:
    def read_batch(group, consumer, stream, count, block_ms) -> list[StreamMessage]: ...
    def ack(group, stream, message_ids) -> None: ...
    def reclaim_pending(group, consumer, stream, idle_ms) -> list[StreamMessage]: ...

class StreamHealthService:
    def stream_info(stream) -> StreamHealthDTO: ...
    def consumer_lag(group, stream) -> int: ...
```

Redis Bridge **不暴露 HTTP**。Stream 积压与 pending 信息写入 Trident Worker 内存态，由 `/health` 统一透出。

---

## 7. 模块三：Trident

### 7.1 定位

核心在线处理服务，分 **Worker**（写库）与 **API**（读库）两个进程，共享 `modules/trident/` 代码。所有持久化逻辑集中在 Worker 的 `persistence_service`，API **只读数据库**，不触达 Worker 内存态。

### 7.2 目录与四层

```text
modules/trident/
├── routes/
│   ├── health_routes.py
│   ├── flow_routes.py
│   └── learner_routes.py
├── controllers/
│   ├── health_controller.py
│   ├── flow_controller.py
│   └── learner_controller.py
├── services/
│   ├── worker_loop.py            # Redis 消费、窗口切分、调度持久化
│   ├── online_engine.py          # 窗口推理（纯内存，不写库）
│   ├── preprocessing.py
│   ├── flow_ingest.py            # Stream 消息 → IngestRecord
│   ├── persistence_service.py    # ★ 唯一写库入口
│   ├── live_flush_service.py     # 周期性快照计算
│   ├── metric_engine.py
│   ├── rule_engine.py
│   ├── risk_scorer.py
│   └── profile_builder.py
└── models/
    ├── ch_flow.py
    ├── pg_learner.py
    ├── pg_learner_snapshot.py
    └── dto/
        ├── ingest_record.py
        ├── flow_row.py
        ├── window_result.py
        └── learner_delta.py
```

**不包含：** CSV 注入、pcap 回放、静态 audit 导出、独立 `pg_session` 表（session 信息放 Worker 内存 + `/health` 透出）。

---

## 8. Trident 数据持久化设计（核心）

### 8.1 设计原则

| 原则 | 说明 |
|------|------|
| 单写入口 | Worker 内只有 `PersistenceService` 调用 models，禁止 service 散落 INSERT |
| 推理与落库分离 | `online_engine` 纯内存；落库在推理完成后一次性组装 |
| 每窗一次 CH 批量写 | 同一窗口内每条 flow **只 INSERT 一次**（含完整分配结果），不做「先写原始、再补分配」两次写入 |
| PG 分两类写入 | **当前态** tick/flush UPSERT `pg_learner`；**历史**仅在学习器更新事件发生时 INSERT `pg_learner_snapshot` |
| 先落库后 ACK | Redis 消息仅在 CH + PG 窗口 tick 均成功后 `XACK` |
| 幂等 | `flow_uid` 全局唯一；PG 以 `session_id + learner_name` UPSERT |

### 8.2 内存态 vs 持久态

```text
┌─────────────────────────────────────────────────────────┐
│ Worker 内存（不落库）                                      │
│  · session_id, window_index                             │
│  · online_engine: 学习器模型、UNKNOWN buffer              │
│  · window_buffer: 当前窗口 IngestRecord[]                │
│  · learner_runtime: 各学习器 flow_count 增量、最近窗口号    │
│  · flush_scheduler: 距上次 flush 的窗口数/秒数            │
└─────────────────────────────────────────────────────────┘
          │ process_window()          │ persist_window()
          ▼                           ▼
┌──────────────────────┐    ┌──────────────────────────────┐
│ WindowResult（DTO）   │    │ ClickHouse ch_flow            │
│  · flows[]           │    │ PostgreSQL pg_learner         │
│  · learner_deltas[]  │    │  · tick UPSERT（每窗，当前态）   │
│  · new_learners[]    │    │  · flush UPSERT（周期性，当前态）│
│                      │    │  · snapshot INSERT（更新事件）   │
└──────────────────────┘    └──────────────────────────────┘
```

### 8.3 单窗口持久化流程

```text
WorkerLoop.run_once()
  │
  ├─1─ read_batch(Redis) → 追加到 window_buffer
  │
  ├─2─ 若未达窗口阈值 → return（不写库、不 ACK）
  │
  ├─3─ preprocessing(window_buffer) → feature_matrix
  │
  ├─4─ online_engine.process_window(records, matrix)
  │       返回 WindowResult { flows[], learner_deltas[], new_learners[] }
  │
  ├─5─ persistence_service.persist_window(result)
  │       ├─ build_flow_rows(result) → ChFlowRow[]
  │       ├─ ch_flow.insert_batch(rows)
  │       ├─ pg_learner.upsert_window_tick(deltas)
  │       ├─ 若有学习器创建/状态变化，pg_learner_snapshot.insert_update_events(...)
  │       └─ 失败则抛错，不 ACK
  │
  ├─6─ redis_bridge.ack(message_ids)
  │
  ├─7─ window_index++
  │
  └─8─ 若 flush_scheduler.should_flush()
          live_flush_service.flush(session_id)
          └─ persistence_service.persist_flush(snapshots)
                ├─ pg_learner.upsert_snapshot(...)        ← 当前态
                └─ 若画像/规则/风险变化，pg_learner_snapshot.insert_update_events(...)
```

### 8.4 `flow_uid` 与 `IngestRecord`

`flow_ingest` 在读 Redis 时构造 `IngestRecord`，**在进入窗口 buffer 前**就算好 `flow_uid`：

```text
优先级：
  1. {stream_key}:{redis_message_id}
  2. sha256(session_id + event_time + src_ip + dst_ip + src_port + dst_port + protocol + mq_message_id)
```

| IngestRecord 字段 | 来源 |
|-------------------|------|
| `flow_uid` | 上述规则 |
| `event_time` | 消息 `event_time`，缺失则用 Redis ID 时间戳 |
| `src_ip` ~ `protocol` | 消息五元组 |
| `features_json` | 消息 `features` 序列化 |
| `feature_profile` | 配置项，默认 `compact_stats_no_env` |
| `mq_type` | 固定 `redis_stream` |
| `mq_topic` | stream key |
| `mq_message_id` | Redis message ID |
| `source_flow_id` | 消息字段，可空 |
| `raw_event` | 原始消息 JSON 字符串 |

### 8.5 `ch_flow` 写入：字段组装

`PersistenceService.build_flow_rows()` 将 `IngestRecord` + `WindowResult` 中每条流的分配结果合并为 **一行完整记录**：

| 字段 | 写入时机 | 值来源 |
|------|----------|--------|
| `session_id` | 每行 | Worker 启动时生成 |
| `flow_uid` | 每行 | IngestRecord |
| `event_time`, `ingest_time` | 每行 | IngestRecord / `now()` |
| 五元组、`features_json`、`feature_profile` | 每行 | IngestRecord |
| `assigned_learner` | 每行 | WindowResult.flows[i] |
| `is_unknown` | 每行 | WindowResult.flows[i] |
| `window_index` | 每行 | 当前窗口序号 |
| `pred_loss`, `threshold` | 每行 | WindowResult.flows[i]，可为 NULL |
| `assignment_meta` | 每行 | JSON：`accepted_learners`、`margin` 等 debug 信息 |
| `mq_*`, `source_flow_id`, `raw_event` | 每行 | IngestRecord |

**Model 调用：**

```python
class ChFlowModel:
    async def insert_batch(rows: list[ChFlowRow]) -> None
    # 仅 INSERT，不做 UPDATE；查询取最新版靠 flow_uid + event_time 或后续 ReplacingMergeTree 优化
```

**批量策略：** 每窗一次 `insert_batch`，默认不分批；单窗超过 10k 行时按 5000 行切片，同一事务语义（全成功或全失败）。

**失败处理：** CH 写入失败 → 不 ACK → 下次 `XREADGROUP` 重读同一批 pending 消息。因 `flow_uid` 稳定，重试可能产生重复行；第一版接受 append-only，查询侧按 `flow_uid` 取 `max(ingest_time)` 去重，后续可改 `ReplacingMergeTree(ingest_time)`。

### 8.6 `pg_learner` 写入：两类 UPSERT

#### A. 窗口 tick（每窗必做）

推理完成后，`WindowResult.learner_deltas[]` 驱动增量更新：

| 字段 | 更新规则 |
|------|----------|
| `flow_count` | `flow_count = pg_learner.flow_count + delta.flow_count` |
| `assignment_share` | 本窗结束后重算：`该学习器累计 flow / session 总 flow` |
| `last_seen_window_index` | 设为当前 `window_index` |
| `last_seen_at` | `now()` |
| `updated_at` | `now()` |
| `learner_status` | 新创建 → `active`；引擎标记 retired → `retired` |
| `creation_window_index` | 仅 `new_learners` 写入 |
| `unknown_absorb_count` | 若有 unknown 聚类吸收 → `+ delta.unknown_absorb` |

**新学习器：** `new_learners[]` 走 `INSERT ... ON CONFLICT (session_id, learner_name) DO UPDATE`，避免并发重复。

```python
class PgLearnerModel:
    async def upsert_window_tick(session_id: str, deltas: list[LearnerDelta]) -> None
```

#### B. Live flush（周期性）

触发条件（满足任一）：

- 每 `live_flush.every_n_windows` 个窗口
- 每 `live_flush.every_n_seconds` 秒
- 本窗有 `new_learners` 创建（立即 flush 新学习器 + 受影响邻居）

对每个 `learner_status = active` 的学习器，从 **内存中该学习器已分配 flow 的滑动窗口样本**（或从 CH 拉最近 N 条，配置决定）计算：

```text
profile_builder.build(flows)   → profile_json
metric_engine.compute(flows)   → metric_json
rule_engine.evaluate(metrics)  → rule_json
risk_scorer.score(rules)       → risk_score, risk_band, risk_reason, risk_version
topology_builder.build(flows)  → topology_json
```

**一次性 UPSERT 快照列：**

```python
class PgLearnerModel:
    async def upsert_snapshot(session_id: str, snapshots: list[LearnerSnapshot]) -> None
```

| 字段 | flush 时写入 |
|------|-------------|
| `profile_json` | 是 |
| `metric_json` | 是 |
| `rule_json` | 是 |
| `topology_json` | 是 |
| `risk_score`, `risk_band`, `risk_reason`, `risk_version` | 是 |
| `flow_count`, `last_seen_*` | 否（由 tick 维护，flush 不覆盖） |

**幂等：** 同一 `(session_id, learner_name)` 反复 flush 只更新 JSON 与 risk 列，不新增行。

**未算风险时：** `risk_score = NULL`，`risk_band = 'UNKNOWN'`，不用 `0` 表示「未计算」。

### 8.7 `pg_learner_snapshot`：学习器更新快照表

`pg_learner` 只保留**当前态**；`pg_learner_snapshot` 只在学习器发生有解释价值的更新时追加一行，形成可查询的历史时间线。

不要每个窗口写一条快照。窗口只是处理节拍，不等于学习器状态发生了值得回放的变化。每窗都写会把 PostgreSQL 压成窗口流水账，也会让历史查询里充满只有 `flow_count` 变化的低价值版本。

第一版建议只在以下事件发生时写快照：

- 学习器创建：`learner_created`
- 学习器状态变化：`status_changed`，例如 `active -> retired`
- 学习器合并或被替换：`merged` / `replaced`
- Live flush 后画像、指标、规则、风险或概览拓扑发生变化：`profile_changed` / `rule_changed` / `risk_changed` / `topology_changed`
- 人工或配置触发的重要重算：`manual_refresh`

如果一次 Live flush 同时产生多个变化，可以合并成一条快照，`update_reasons` 保存多个原因。

#### 表结构

```sql
CREATE TABLE pg_learner_snapshot (
  id                    BIGSERIAL PRIMARY KEY,
  session_id            VARCHAR(256) NOT NULL,
  learner_name          VARCHAR(512) NOT NULL,

  window_index          BIGINT NOT NULL,
  -- 触发本次学习器更新时的窗口编号

  update_event_id       VARCHAR(512) NOT NULL,
  -- 幂等事件 ID，由 session_id、learner_name、window_index、update_reasons、state_hash 生成

  update_reasons        JSONB NOT NULL,
  -- 例如 ["learner_created", "risk_changed"]

  state_hash            VARCHAR(128),
  -- 本次快照核心状态的哈希，用于判断 Live flush 后是否真的变化

  assignment_share      DOUBLE PRECISION,
  flow_count            BIGINT,
  learner_status        VARCHAR(16),
  unknown_absorb_count  BIGINT,

  -- 学习器解释快照
  profile_json          JSONB,
  metric_json           JSONB,
  rule_json             JSONB,
  topology_json         JSONB,
  risk_score            DOUBLE PRECISION,
  risk_band             VARCHAR(32),
  risk_reason           TEXT,
  risk_version          VARCHAR(64),

  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (session_id, learner_name, update_event_id)
);

CREATE INDEX idx_snapshot_session_learner
  ON pg_learner_snapshot (session_id, learner_name, created_at DESC);

CREATE INDEX idx_snapshot_session_window
  ON pg_learner_snapshot (session_id, window_index DESC);

CREATE INDEX idx_snapshot_reasons_gin
  ON pg_learner_snapshot USING GIN (update_reasons);
```

**约束说明：**

| 约束 | 含义 |
|------|------|
| `UNIQUE (session_id, learner_name, update_event_id)` | 同一个学习器更新事件只记录一次，保证重试幂等 |
| `id BIGSERIAL` | 全局递增主键，用于稳定排序 |
| `window_index` | 用于把历史流量与当时学习器状态对齐 |
| `created_at` | 用于按时间查询最近一次快照 |

#### 什么时候写快照

窗口 tick 仍然更新 `pg_learner` 当前态，例如 `flow_count`、`assignment_share`、`last_seen_at`。但仅有计数变化时，不写 `pg_learner_snapshot`。

`persist_window` 只在以下情况写快照：

- `new_learners[]` 非空，记录新学习器创建后的状态。
- 学习器被标记为 `retired`、`merged` 或其它生命周期状态变化。
- unknown 聚类吸收导致学习器语义发生变化，且需要历史解释。

`persist_flush` 在计算出 `profile_json`、`metric_json`、`rule_json`、`topology_json`、`risk_*` 后，先与 `pg_learner` 当前行对比。如果核心解释状态没有变化，只更新 `updated_at` 或跳过；如果有变化，先 UPSERT `pg_learner` 当前态，再 INSERT 一条 `pg_learner_snapshot`。

核心解释状态建议参与 `state_hash`：

```text
state_hash = sha256(
  learner_status
  + profile_json
  + metric_json
  + rule_json
  + topology_json
  + risk_score
  + risk_band
  + risk_version
)
```

同一学习器连续两次 flush 如果 `state_hash` 相同，不写新快照。

#### 快照内容

每条快照保存“更新发生后”的学习器解释状态：

| 字段 | 值 |
|------|-----|
| `window_index` | 触发更新时的窗口 |
| `update_event_id` | 幂等事件 ID |
| `update_reasons` | 本次更新原因数组 |
| `state_hash` | 核心解释状态哈希 |
| `flow_count`, `assignment_share`, `learner_status`, `unknown_absorb_count` | 更新后的当前值 |
| `profile_json` ~ `topology_json` | 更新后的解释快照，可为空 |
| `risk_*` | 更新后的风险字段，可为空 |

**append-only：** 历史快照只做 INSERT，不做 UPDATE。重试时用 `ON CONFLICT (session_id, learner_name, update_event_id) DO NOTHING`。

#### 与 `pg_learner` 的分工

```text
pg_learner           → 前端列表/详情默认读这里（最新态，单行）
pg_learner_snapshot  → 历史解释、审计、查询过去某段流量时还原当时的学习器状态
```

更新顺序始终是：**先写 `pg_learner`（当前态）→ 再写 `pg_learner_snapshot`（历史）**。历史写入失败策略见 8.10。

#### 保留与清理

配置项 `snapshot.retain_days`（默认 30）：

- 定时任务 `SnapshotRetentionService` 删除 `created_at < now() - retain_days` 的行
- 仅清历史表，不影响 `pg_learner`
- 第一版可按 session 维度清理；多 session 并存时用 `session_id` 过滤

### 8.8 `PersistenceService` 接口

```python
class PersistenceService:
    """Worker 内唯一写库协调器。"""

    async def persist_window(self, result: WindowResult) -> None:
        """CH 批量 INSERT + pg_learner 当前态 UPSERT + 必要的学习器更新快照。"""

    async def persist_flush(self, snapshots: list[LearnerSnapshot]) -> None:
        """pg_learner 快照 UPSERT + 发生变化时写学习器更新快照。"""
```

Controller / API **不得**调用此类；仅 `WorkerLoop` 与 `LiveFlushService` 调用。

### 8.9 完整时序（单条 flow）

```text
T0   Suricata XADD suricata:cic_flow
T1   Worker XREADGROUP → flow_ingest → IngestRecord 入 window_buffer
T2   窗口满 → online_engine.process_window()
T3   PersistenceService.persist_window()
       → ch_flow INSERT
       → pg_learner UPSERT tick
       → 如有学习器创建/状态变化，INSERT pg_learner_snapshot
T4   XACK
---
T5   flush_scheduler 触发
T6   LiveFlushService 计算 JSON
T7   PersistenceService.persist_flush()
       → pg_learner UPSERT 快照列（当前态）
       → 如画像/规则/风险/拓扑变化，INSERT pg_learner_snapshot
```

### 8.10 写入失败与恢复

| 失败点 | 行为 |
|--------|------|
| CH insert 失败 | 不 ACK；pending 消息保留；下轮重试整窗 |
| PG tick 失败 | 不 ACK；CH 已写入则产生 orphan flow 行 |
| 学习器更新快照 INSERT 失败 | 若发生在窗口持久化内，不 ACK；若发生在 flush 内，记录告警并下轮重试 |
| PG flush 当前态失败 | 不影响 ACK；下轮 flush 重试；不写学习器更新快照 |
| PG flush 快照 INSERT 失败 | 当前态已更新；记录告警；下轮 flush 如果 state_hash 仍不同则补写新快照 |
| Worker 崩溃 | Redis pending 由 `XAUTOCLAIM` 回收；快照靠 `update_event_id` 唯一约束幂等 |

Graceful shutdown：处理完当前窗口 → `persist_window` → `persist_flush`（可选）→ ACK → 退出。

### 8.11 Models 层（只负责 SQL）

```python
class ChFlowModel:
    async def insert_batch(rows: list[ChFlowRow]) -> None
    async def query(filters: FlowQueryFilters) -> list[FlowRow]

class PgLearnerModel:
    async def upsert_window_tick(session_id: str, deltas: list[LearnerDelta]) -> None
    async def upsert_snapshot(session_id: str, snapshots: list[LearnerSnapshot]) -> None
    async def list_learners(filters: LearnerQueryFilters) -> list[LearnerRow]
    async def get_learner(session_id: str, name: str) -> LearnerRow | None

class PgLearnerSnapshotModel:
    async def insert_update_events(session_id: str, rows: list[LearnerSnapshot]) -> None
    async def list_snapshots(filters: SnapshotQueryFilters) -> list[SnapshotRow]
    async def get_snapshot(session_id: str, learner_name: str, snapshot_id: int) -> SnapshotRow | None
    async def delete_older_than(cutoff: datetime, session_id: str | None = None) -> int
```

JSON 列由 service 序列化为 `dict` 后传入 model；model 不做业务计算。

---

## 9. HTTP 接口（精简）

**仅 Trident API 暴露 5 个读接口 + 1 个健康检查。** Suricata / Redis 不单独开 HTTP。

前缀：`/api/v1`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | Worker 存活、session_id、Redis lag、DB 连通 |
| GET | `/flows` | 流列表（含分配结果） |
| GET | `/learners` | 学习器列表（含 risk 字段，可筛选排序） |
| GET | `/learners/{name}` | 学习器详情（**当前态**，四类 JSON 快照） |
| GET | `/learners/{name}/snapshots` | 学习器**历史快照**时间线 |

### 9.1 GET `/health`

```json
{
  "status": "ok",
  "session_id": "trident-prod-20260526-001",
  "worker": { "uptime_seconds": 3600, "window_index": 1024 },
  "redis": { "stream_lag": 120, "pending_count": 0 },
  "database": { "clickhouse": "ok", "postgres": "ok" }
}
```

### 9.2 GET `/flows`

| 参数 | 必填 | 说明 |
|------|------|------|
| `session_id` | 否 | 默认当前 Worker session |
| `start_time`, `end_time` | 否 | ISO8601 |
| `assigned_learner` | 否 | 按学习器过滤 |
| `is_unknown` | 否 | `0` / `1` |
| `limit` | 否 | 默认 100，最大 1000 |
| `offset` | 否 | 默认 0 |

响应：`{ "items": [...], "total": N }`，每项含 `flow_uid`、五元组、`assigned_learner`、`is_unknown`、`window_index`、`event_time`。

> 原 `/learners/{name}/flows` 合并为此接口，传 `assigned_learner={name}` 即可。

### 9.3 GET `/learners`

| 参数 | 必填 | 说明 |
|------|------|------|
| `session_id` | 否 | 默认当前 session |
| `status` | 否 | `active` / `retired` / … |
| `risk_band` | 否 | `HIGH` / `MEDIUM` / `LOW` / `UNKNOWN` |
| `sort` | 否 | `risk_score` / `flow_count` / `updated_at`（默认 `risk_score desc`） |
| `limit`, `offset` | 否 | 分页 |

响应：列表项含 `learner_name`、`flow_count`、`risk_score`、`risk_band`、`learner_status`、`updated_at`。

> 原 `/risks` 合并为此接口，传 `risk_band=HIGH&sort=risk_score` 即可。

### 9.4 GET `/learners/{name}`

返回 `pg_learner` **当前态**完整行：`profile_json`、`metric_json`、`rule_json`、`topology_json`、`risk_reason` 等。

> 查历史版本用 `/snapshots`，不在此接口混返。

### 9.5 GET `/learners/{name}/snapshots`

| 参数 | 必填 | 说明 |
|------|------|------|
| `session_id` | 否 | 默认当前 session |
| `reason` | 否 | 按更新原因过滤，如 `risk_changed` / `learner_created` |
| `window_from`, `window_to` | 否 | 按 `window_index` 范围 |
| `time_from`, `time_to` | 否 | 按 `created_at` 范围 |
| `limit` | 否 | 默认 50，最大 500 |
| `offset` | 否 | 默认 0 |

响应示例：

```json
{
  "items": [
    {
      "id": 42,
      "window_index": 1024,
      "update_reasons": ["learner_created"],
      "flow_count": 128394,
      "assignment_share": 0.23,
      "learner_status": "active",
      "created_at": "2026-05-26T10:20:30Z"
    },
    {
      "id": 41,
      "window_index": 1020,
      "update_reasons": ["risk_changed", "rule_changed"],
      "flow_count": 127194,
      "risk_score": 0.82,
      "risk_band": "HIGH",
      "profile_json": { "...": "..." },
      "metric_json": { "...": "..." },
      "rule_json": { "...": "..." },
      "topology_json": { "...": "..." },
      "created_at": "2026-05-26T10:18:00Z"
    }
  ],
  "total": 2
}
```

排序：默认 `created_at DESC, id DESC`（最新版本在前）。需要按窗口回放时用 `window_index ASC, id ASC`。

可选：传 `snapshot_id={id}` 查单条详情（与列表合并为同一 endpoint 的 query 参数，不另开路由）。

### 9.6 四层映射

```text
GET /flows                    → FlowController      → FlowQueryService           → ChFlowModel
GET /learners                 → LearnerController   → LearnerQueryService        → PgLearnerModel
GET /learners/{name}          → LearnerController   → LearnerQueryService        → PgLearnerModel
GET /learners/{name}/snapshots→ LearnerController   → LearnerSnapshotQueryService→ PgLearnerSnapshotModel
GET /health                   → HealthController    → HealthService              → （Worker 心跳 + DB ping）
```

---

## 10. 配置项

### 10.1 `config/trident.yaml`

```yaml
session:
  id: ""                          # 空则启动时自动生成
  deployment_id: "prod-01"

input:
  redis:
    url: "redis://127.0.0.1:6379/0"
    stream: "suricata:cic_flow"
    consumer_group: "trident-online"
    consumer_name: ""             # 空则 hostname-pid
    batch_size: 500
    block_ms: 2000
    ack: true

window:
  mode: "count"                   # count | time
  size: 5000
  max_wait_seconds: 30

output:
  redis:
    assignments_stream: "trident:assignments"
    metrics_stream: "trident:metrics"
    emit_assignments: false
    emit_metrics: true

database:
  clickhouse:
    dsn: "clickhouse://localhost:8123/default"
  postgres:
    dsn: "postgresql://user:pass@localhost:5432/streamtrident"

live_flush:
  every_n_windows: 10
  every_n_seconds: 60

snapshot:
  retain_days: 30                 # pg_learner_snapshot 保留天数
  enabled: true
  write_on_create: true
  write_on_status_change: true
  write_on_profile_change: true
  write_on_rule_change: true
  write_on_risk_change: true

risk:
  version: "rule_weighted_v1"
```

### 10.2 明确禁止的配置项

- `csv_path`、`pcap_path`、`dataset`、`inject_*`
- `benchmark`、`visualization`、`export_dir`
- `ground_truth_*`、`label_column`

---

## 11. 进程与部署

```text
# 1. Redis（独立运维）
redis-server

# 2. Suricata 服务
suricata -c /etc/suricata/suricata.yaml -i eth1
python -m app.modules.suricata.writer --config config/suricata.yaml

# 3. Trident Worker（消费 + 写库）
python -m app.worker --config config/trident.yaml

# 4. Trident API（查询）
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

三模块独立重启：

| 事件 | 影响 |
|------|------|
| Suricata 重启 | Redis 继续收消息；Trident 不受影响 |
| Redis 重启 | Suricata 写入失败需重连；Trident 消费暂停 |
| Trident Worker 重启 | Redis backlog 上升；恢复后继续 XREADGROUP；session_id 可配置续跑或新 session |
| Trident API 重启 | 仅查询中断，Worker 不受影响 |

---

## 12. 模块间依赖规则

```text
suricata.services.stream_publisher
    → redis_bridge.services.stream_writer   （仅 XADD 输入流）

trident.services.* 
    → redis_bridge.services.stream_reader   （XREADGROUP / XACK）
    → trident.models.*                      （CH / PG）

trident.routes.*
    → trident.controllers.*
    → trident.services.* （只读查询）
    → trident.models.*

禁止：
  suricata → trident （采集侧不得依赖推理侧）
  trident API → online_engine 内存态直接读取（查询必须走 DB）
  任意模块 → 外部 demo / pipeline / visualize 包
```

---

## 13. 风险与规则（Service 层，非 Model）

实时场景无标签，风险仅来自无监督画像 + 指标 + 规则：

```text
risk_score = clamp(
  sum(rule_weight * match_strength * confidence) / sum(rule_weight),
  0, 1
)
```

| risk_score | risk_band |
|------------|-----------|
| NULL | UNKNOWN |
| >= 0.75 | HIGH |
| >= 0.45 | MEDIUM |
| < 0.45 | LOW |

`risk_version` 固定绑定公式版本（如 `rule_weighted_v1`）。定性标签（如协议簇类型）只进 `profile_json` / `rule_json`，**不做固定列、不做有监督分类输出**。

---

## 14. 实施阶段

| 阶段 | 内容 | 交付 |
|------|------|------|
| P0 | migrations + models + redis_bridge | CH/PG 表可用；Stream 读写通 |
| P1 | `PersistenceService.persist_window` + WorkerLoop | 每窗 CH + pg_learner 当前态；学习器创建/状态变化时写快照 |
| P2 | online_engine 完整窗口闭环 | 分配与学习器生命周期 |
| P3 | LiveFlushService + `persist_flush` + 更新事件快照 | pg_learner 当前态 + 变化时写 pg_learner_snapshot |
| P4 | 5 个读 API + health | `/api/v1/*` |
| P5 | suricata writer 联调 | 三模块端到端 |
| P6 | XAUTOCLAIM、graceful shutdown、snapshot  retention | 生产就绪 |

---

## 15. 技术选型建议

| 项 | 建议 | 理由 |
|----|------|------|
| 语言 | Python 3.11+ | 与流式 ML 生态衔接；本设计不绑定具体 ML 框架 |
| API 框架 | FastAPI | 异步、OpenAPI 自动生成 |
| CH 驱动 | clickhouse-connect / asynch | 批量 INSERT |
| PG 驱动 | asyncpg / SQLAlchemy 2 async | UPSERT + JSONB |
| Redis | redis-py asyncio | Stream 原生支持 |
| 配置 | YAML + pydantic-settings | 与环境变量合并 |

---

## 16. 与原文档的映射（概念级，无代码引用）

| 原架构概念 | 本项目中位置 |
|------------|--------------|
| Suricata → Redis Stream | `modules/suricata` + `redis_bridge` |
| Trident Redis consumer | `app/worker.py` + `trident/services/online_engine` |
| runtime preprocessing | `trident/services/preprocessing.py` |
| Live flush | `trident/services/live_flush_service.py` |
| 写库唯一入口 | `trident/services/persistence_service.py` |
| ch_flow / pg_learner | `trident/models/ch_flow.py` / `pg_learner.py` |
| 历史快照 | `trident/models/pg_learner_snapshot.py` |
| 查询 API（5+1） | `trident/routes/*` |
| consumer group / pending | `redis_bridge/services/consumer_group_manager.py` |

本文档仅描述新仓库边界与分层，**不包含对任何既有仓库路径、模块名、脚本的 import 或 subprocess 调用**。
