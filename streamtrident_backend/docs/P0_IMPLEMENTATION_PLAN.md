# StreamTrident Backend P0 落地方案

本文档是 `DESIGN.md` 的 P0 执行版。目标不是一次性落完整 Trident，而是先落地一个可运行、可恢复、可查询的最小实时闭环。

P0 必须遵守 `DESIGN.md` 的架构边界：

- 三模块：Suricata、Redis Bridge、Trident。
- 四层：`routes -> controllers -> services -> models`。
- Worker/API 分离：Worker 写库，API 只读库。
- 单写入口：只有 `PersistenceService` 协调 ClickHouse 和 PostgreSQL 写入。
- 双核心表：`ch_flow` 保存流事实，`pg_learner` 保存学习器当前态。

---

## 1. P0 目标

P0 只回答一个问题：实时流量能否从 Redis Stream 被 Trident 稳定消费，并形成可查询的流事实和学习器当前态。

闭环如下：

```text
Suricata / suricata-writer
  -> Redis Stream: suricata:cic_flow
  -> Trident Worker
  -> OnlineEngine.process_window()
  -> PersistenceService.persist_window()
  -> ClickHouse ch_flow
  -> PostgreSQL pg_learner
  -> Trident API 查询
```

P0 完成后，系统应该能够：

- 从 Redis Stream 持续读取 flow 消息。
- 按窗口组织输入流。
- 对每条 flow 产生 `assigned_learner`、`is_unknown`、`pred_loss`、`threshold` 等最小分配结果。
- 每个窗口只向 `ch_flow` 写入一次完整 flow 记录。
- 更新 `pg_learner` 的当前态计数和生命周期字段。
- 在写库成功后再 ACK Redis 消息。
- 通过 API 查询 flow 列表、learner 列表、learner 详情和 health。

---

## 2. P0 不做什么

这些能力不进入 P0，避免第一版落地失控：

- 不做 Live flush。
- 不计算 `profile_json`、`metric_json`、`rule_json`、`topology_json`。
- 不计算 `risk_score`、`risk_band`、`risk_reason`。
- 不写 `pg_learner_snapshot`。
- 不做 IP 中心拓扑接口。
- 不做历史解释查询。
- 不做 Suricata 进程托管和复杂健康管理。
- 不做压测、benchmark、离线回放、CSV/PCAP 导入。
- 不接前端可视化。

P0 可以创建 `pg_learner_snapshot` migration 占位，但默认不写。学习器更新快照从 P1/P2 开始实现。

---

## 3. P0 目录落地

P0 只实现 `DESIGN.md` 目录中的最小子集。

```text
streamtrident_backend/
├── config/
│   ├── redis_bridge.yaml
│   └── trident.yaml
├── app/
│   ├── main.py
│   ├── worker.py
│   ├── common/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── exceptions.py
│   │   └── db/
│   │       ├── clickhouse_pool.py
│   │       └── postgres_pool.py
│   └── modules/
│       ├── redis_bridge/
│       │   ├── services/
│       │   │   ├── stream_reader.py
│       │   │   ├── consumer_group_manager.py
│       │   │   └── stream_health.py
│       │   └── models/
│       │       └── redis_client.py
│       └── trident/
│           ├── routes/
│           │   ├── health_routes.py
│           │   ├── flow_routes.py
│           │   └── learner_routes.py
│           ├── controllers/
│           │   ├── health_controller.py
│           │   ├── flow_controller.py
│           │   └── learner_controller.py
│           ├── services/
│           │   ├── worker_loop.py
│           │   ├── flow_ingest.py
│           │   ├── preprocessing.py
│           │   ├── online_engine.py
│           │   ├── persistence_service.py
│           │   ├── flow_query_service.py
│           │   └── learner_query_service.py
│           └── models/
│               ├── ch_flow.py
│               ├── pg_learner.py
│               └── dto/
│                   ├── ingest_record.py
│                   ├── flow_row.py
│                   ├── window_result.py
│                   └── learner_delta.py
└── migrations/
    ├── clickhouse/
    │   └── 001_ch_flow.sql
    └── postgres/
        ├── 001_pg_learner.sql
        └── 002_pg_window_commit.sql
```

P0 暂不创建 `modules/suricata/routes/controllers`。Suricata 侧只要求能向 Redis Stream 写入符合契约的消息。

---

## 4. 数据库落地

### 4.1 ClickHouse `ch_flow`

P0 必须建 `ch_flow`。它是历史 flow 事实表，也是后续 IP 拓扑查询的数据源。

必需字段：

```text
session_id
flow_uid
event_time
ingest_time
src_ip
dst_ip
src_port
dst_port
protocol
feature_profile
features_json
assigned_learner
is_unknown
window_index
pred_loss
threshold
assignment_meta
mq_type
mq_topic
mq_message_id
source_flow_id
raw_event
```

P0 写入策略：

- 每个窗口组装完整行后批量 INSERT。
- 不做 UPDATE。
- 重试可能产生重复行，查询侧按 `flow_uid` 取最新 `ingest_time` 去重。
- 不承诺跨多个 ClickHouse 批次的事务语义。

### 4.2 PostgreSQL `pg_learner`

P0 必须建 `pg_learner`。它是学习器当前态表。

P0 必需字段：

```text
id
session_id
learner_name
learner_status
creation_window_index
last_seen_window_index
created_at
last_seen_at
updated_at
flow_count
assignment_share
unknown_absorb_count
profile_json
metric_json
rule_json
topology_json
risk_score
risk_band
risk_reason
risk_version
```

P0 中 JSON 和风险字段可以为空：

- `profile_json = NULL`
- `metric_json = NULL`
- `rule_json = NULL`
- `topology_json = NULL`
- `risk_score = NULL`
- `risk_band = 'UNKNOWN'`
- `risk_version = 'unset'`

P0 只维护：

- `learner_name`
- `learner_status`
- `creation_window_index`
- `last_seen_window_index`
- `last_seen_at`
- `updated_at`
- `flow_count`
- `assignment_share`
- `unknown_absorb_count`

---

## 5. Redis Stream 契约

P0 只消费一个输入 Stream：

```text
suricata:cic_flow
```

消息格式：

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

P0 要求：

- 缺失 `event_time` 时用 Redis message id 推导时间。
- 缺失 `source_flow_id` 时写空字符串。
- `features` 原样序列化为 `features_json`。
- 原始消息整体序列化为 `raw_event`。
- `flow_uid` 优先使用 `{stream_key}:{redis_message_id}`。

---

## 6. Worker 落地流程

### 6.1 启动

`app/worker.py` 负责启动 Worker。

启动步骤：

```text
1. 加载 config/trident.yaml
2. 生成或读取 session_id
3. 初始化 Redis / ClickHouse / PostgreSQL 连接池
4. 创建 Redis Consumer Group，不存在则创建
5. 初始化 WorkerLoop
6. 进入持续消费循环
```

### 6.2 消费循环

`WorkerLoop.run_once()` 是 P0 的主循环单元。

```text
1. StreamReaderService.read_batch()
2. FlowIngestService.to_ingest_records()
3. 追加到 window_buffer
4. 如果窗口未满，返回等待下一批
5. preprocessing.build_feature_matrix()
6. OnlineEngine.process_window()
7. PersistenceService.persist_window()
8. StreamReaderService.ack()
9. 清空当前窗口 buffer
10. window_index += 1
```

P0 窗口只需要支持 count mode：

```yaml
window:
  mode: "count"
  size: 5000
  max_wait_seconds: 30
```

如果 `max_wait_seconds` 到达但窗口未满，也应触发处理，避免低流量时长期不落库。

---

## 7. OnlineEngine P0 策略

P0 不要求完整复刻复杂 Trident 学习器逻辑，但必须保留接口形状，便于后续替换成完整实现。

`OnlineEngine.process_window(records, matrix)` 输出：

```text
WindowResult
  flows[]
  learner_deltas[]
  new_learners[]
```

P0 可采用最小策略：

- 先内置一个 `BASELINE` 学习器。
- 所有可解析 flow 默认分配给 `BASELINE`。
- 特征缺失严重或模型拒绝时分配为 unknown。
- 如果已有完整 Trident 核心可接入，则只通过 `OnlineEngine` 适配，不允许 Worker 直接调用算法细节。

P0 的重点不是检测效果，而是打通实时工程闭环。

每条 flow 的 P0 输出字段：

```text
flow_uid
assigned_learner
is_unknown
pred_loss
threshold
assignment_meta
```

其中 `pred_loss`、`threshold` 可以为空，但字段必须保留。

---

## 8. PersistenceService P0 设计

`PersistenceService` 是 P0 唯一写库入口。

```python
class PersistenceService:
    async def persist_window(self, result: WindowResult) -> None:
        ...
```

内部顺序：

```text
1. build_flow_rows(result)
2. ChFlowModel.insert_batch(rows)
3. PgLearnerModel.upsert_window_tick(...)
4. 返回成功
```

P0 不调用：

```text
PgLearnerSnapshotModel.insert_update_events()
LiveFlushService.flush()
RiskScorer.score()
TopologyBuilder.build()
```

### 8.1 幂等要求

P0 必须解决 Redis 重放导致 `pg_learner.flow_count` 重复累加的问题。

推荐方案：新增轻量窗口处理记录表 `pg_window_commit`。

```sql
CREATE TABLE pg_window_commit (
  session_id      VARCHAR(256) NOT NULL,
  window_index    BIGINT NOT NULL,
  committed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  flow_count      BIGINT NOT NULL,
  PRIMARY KEY (session_id, window_index)
);
```

`persist_window()` 中 PostgreSQL 侧事务顺序：

```text
1. INSERT pg_window_commit(session_id, window_index, flow_count)
   ON CONFLICT DO NOTHING
2. 如果 insert 影响行数为 0，说明该窗口已提交：
   - 不再累加 pg_learner
   - 直接返回 PG 成功
3. 如果 insert 成功：
   - 执行 pg_learner upsert_window_tick
   - 提交事务
```

这样即使 Worker 在 ACK 前崩溃，Redis 重放同一窗口，也不会重复累加学习器计数。

注意：`pg_window_commit` 是 P0 的工程幂等表，不是业务查询中心。后续如果采用更完整的窗口状态表，可以再合并。

### 8.2 失败处理

| 失败点 | P0 行为 |
|--------|---------|
| Redis read 失败 | 记录错误，退避重试 |
| preprocessing 失败 | 本窗口失败，不 ACK，等待人工或错误队列策略 |
| CH insert 失败 | 不写 PG，不 ACK，下轮重试 |
| PG upsert 失败 | 不 ACK；CH 可能已有重复行，查询侧按 `flow_uid` 去重 |
| ACK 失败 | 下轮可能重放；PG 由 `pg_window_commit` 防重复累加 |
| Worker 崩溃 | Redis pending 由后续 XAUTOCLAIM 或同 consumer 恢复 |

---

## 9. Models P0 职责

### 9.1 `ChFlowModel`

允许：

- `insert_batch(rows)`
- `query(filters)`

禁止：

- 计算学习器分配。
- 修改 `pg_learner`。
- 理解风险规则。

### 9.2 `PgLearnerModel`

允许：

- `upsert_window_tick(session_id, window_index, deltas)`
- `list_learners(filters)`
- `get_learner(session_id, learner_name)`

禁止：

- 计算 profile / metric / rule / risk。
- 写历史快照。
- 直接读取 Redis。

### 9.3 `RedisClientModel`

允许：

- 创建 Redis 连接池。
- 暴露底层连接给 Redis Bridge services。

禁止：

- 在 model 层组织业务消费循环。

---

## 10. API P0

P0 暴露 4 个读接口和 1 个健康接口。

前缀：

```text
/api/v1
```

接口：

| 方法 | 路径 | 数据源 | P0 用途 |
|------|------|--------|---------|
| GET | `/health` | Redis + DB ping + Worker heartbeat | 判断链路是否存活 |
| GET | `/flows` | `ch_flow` | 查询流事实和分配结果 |
| GET | `/learners` | `pg_learner` | 查询学习器当前列表 |
| GET | `/learners/{name}` | `pg_learner` | 查询单个学习器当前态 |

P0 不实现：

- `/learners/{name}/snapshots`
- `/topology/ip`
- `/risks`

### 10.1 session_id 规则

P0 为了避免 API 读取 Worker 内存，查询接口默认要求显式传 `session_id`。

```text
GET /api/v1/flows?session_id=...
GET /api/v1/learners?session_id=...
```

`/health` 可以返回 API 配置中的 `default_session_id`，但业务查询不要隐式依赖 Worker 当前内存态。

---

## 11. 配置 P0

`config/trident.yaml` P0 最小配置：

```yaml
session:
  id: ""
  deployment_id: "dev-01"

input:
  redis:
    url: "redis://127.0.0.1:6379/0"
    stream: "suricata:cic_flow"
    consumer_group: "trident-online"
    consumer_name: ""
    batch_size: 500
    block_ms: 2000
    ack: true

window:
  mode: "count"
  size: 5000
  max_wait_seconds: 30

database:
  clickhouse:
    dsn: "clickhouse://localhost:8123/default"
  postgres:
    dsn: "postgresql://user:pass@localhost:5432/streamtrident"

p0_engine:
  default_learner: "BASELINE"
  unknown_on_parse_error: true

api:
  default_session_id: ""
```

P0 不启用：

```yaml
live_flush:
  enabled: false

snapshot:
  enabled: false

risk:
  enabled: false
```

---

## 12. 验收标准

P0 通过的最低标准：

1. Redis 中连续写入 1000 条符合契约的 flow 消息。
2. Worker 能消费并处理这些消息。
3. `ch_flow` 中能查到对应 flow，且包含五元组、特征 JSON、分配结果、MQ 溯源字段。
4. `pg_learner` 中能查到 `BASELINE` 或实际学习器当前态。
5. `/api/v1/flows?session_id=...` 能返回 flow 列表。
6. `/api/v1/learners?session_id=...` 能返回 learner 列表。
7. Worker 在 PG 更新成功但 ACK 前崩溃后，重放同一窗口不会重复累加 `flow_count`。
8. CH 重复写入时，查询接口能按 `flow_uid` 返回去重后的结果。
9. 不需要任何 CSV、PCAP、离线 run、标签字段或实验输出目录。

---

## 13. P0 实施顺序

建议按以下顺序落地：

| 顺序 | 内容 | 验收 |
|------|------|------|
| 1 | 配置加载、日志、异常基类 | Worker/API 能启动并读取配置 |
| 2 | Redis Bridge：连接、group 创建、read、ack、health | 能读写 `suricata:cic_flow` |
| 3 | ClickHouse / PostgreSQL 连接池 | DB ping 正常 |
| 4 | migrations：`ch_flow`、`pg_learner`、`pg_window_commit` | 表结构可创建 |
| 5 | DTO：`IngestRecord`、`WindowResult`、`LearnerDelta`、`ChFlowRow` | 类型边界清晰 |
| 6 | `flow_ingest` + `preprocessing` | Stream 消息能变成窗口输入 |
| 7 | `online_engine` P0 baseline 策略 | 每条 flow 有分配结果 |
| 8 | `PersistenceService.persist_window` | 一个窗口能写 CH + PG |
| 9 | WorkerLoop | 持续消费、窗口触发、成功后 ACK |
| 10 | 查询 models/services/controllers/routes | 4 个 API 可用 |
| 11 | 崩溃重放测试 | `flow_count` 不重复累加 |

---

## 14. P0 到 P1 的升级点

P0 稳定后，再进入 P1/P2：

- 接入完整 Trident 在线学习器逻辑。
- 实现 Live flush。
- 写入 `profile_json`、`metric_json`、`rule_json`、`topology_json`。
- 计算 `risk_score`、`risk_band`、`risk_reason`、`risk_version`。
- 在学习器创建、状态变化、画像/规则/风险变化时写 `pg_learner_snapshot`。
- 增加 `/learners/{name}/snapshots`。
- 增加 IP 中心拓扑接口。

P0 的原则是先让实时链路站稳，再逐步加入解释和历史能力。
