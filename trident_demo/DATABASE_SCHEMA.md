# Trident Demo 数据库设计（ClickHouse + PostgreSQL）

本文档为 `trident_demo` **生产化主流程** 的双库表结构设计，对齐：

1. **主流程**：Suricata 网卡抓包 → 消息队列（Redis Stream / Kafka）→ Trident 消费 → 推理 / 建学习器 / 流分配 → 规则层指标 + 定性  
2. **前端**：[`V3-ui`](../V3-ui) 总览、学习器详情、Run 对比、风险列表等页面  

**分工原则**

| 库 | 存什么 | 原因 |
|----|--------|------|
| **ClickHouse** | 原始流、五元组、特征向量、逐流分配、窗口时序 | 高吞吐写入、按 run/时间范围扫描、聚合 |
| **PostgreSQL** | Run 元数据、学习器、指标审计、规则匹配、拓扑 JSON、风险条目、配置 | 事务、JOIN、JSONB、UI 列表/详情低延迟点查 |

---

## 1. 端到端数据流

```mermaid
flowchart LR
  subgraph ingest [采集层]
    nic[网卡]
    suri[Suricata cic_flow]
    mq[(消息队列)]
  end

  subgraph trident [Trident Demo]
    consumer[流消费者]
    infer[推理 tSieve]
    cluster[聚类 tMagnifier]
    assign[流分配]
    qualify[规则层 qualification]
  end

  subgraph storage [存储]
    ch[(ClickHouse)]
    pg[(PostgreSQL)]
  end

  subgraph ui [V3-ui]
    overview[总览 GraphAnalysis]
    learner[学习器详情]
    compare[Runs 对比]
    risk[风险列表]
  end

  nic --> suri --> mq --> consumer --> infer --> cluster --> assign
  assign --> ch
  assign --> qualify --> pg
  consumer --> ch
  pg --> ui
  ch --> ui
```

**写入时机**

| 阶段 | 写入目标 | 说明 |
|------|----------|------|
| Suricata 产出 EVE | ClickHouse `ch_flow_raw` | 每条流一条，含稳定 `flow_uid`、时间戳、五元组、特征 |
| Trident 消费 MQ | 同上（或 MQ offset 标记） | `ingest_source=suricata` |
| 窗口推理结束 | ClickHouse `ch_flow_assignment` | 每条流 → `learner_name` |
| 窗口推理结束 | ClickHouse `ch_window_stats` | 学习器数、unknown buffer |
| 学习器创建/增量 | PostgreSQL `pg_learner` | 学习器生命周期 |
| Run 结束 / Live flush | PostgreSQL `pg_learner_metric` / `pg_learner_rule` | 22 项指标 + 规则匹配 |
| Run 结束 | PostgreSQL `pg_run` / `pg_run_summary` | 供 Runs 列表与对比 |
| 规则强匹配 attack | PostgreSQL `pg_risk_alert` | 映射 V3-ui 风险列表（可选自动建） |

---

## 2. 与 V3-ui 页面对照

| V3-ui 页面 | 当前读盘文件 | 迁移后数据源 |
|------------|--------------|--------------|
| **总览** `GraphAnalysisPage` | `learner_count_over_time.csv` | ClickHouse `ch_window_stats` |
| | `learner_label_distribution.csv` | PostgreSQL `pg_learner` + `pg_learner_label_stat` + `pg_learner_profile_feature` |
| | `debug_true_overlap_pairs.csv` | PostgreSQL `pg_learner_overlap` 或 CH 物化 |
| | `dataset_network_topology.json` | PostgreSQL `pg_artifact_blob` |
| | `learner_network_topology.json` | PostgreSQL `pg_artifact_blob` |
| | `metrics.json` / `performance_metrics.json` | PostgreSQL `pg_run_summary` |
| **学习器详情** `LearnerDetailPage` | `learner_topology_metric_audit.json` | PostgreSQL `pg_learner_metric` + `pg_learner_rule` + `pg_learner_hint` |
| | `learner_network_topology.json` | PostgreSQL `pg_artifact_blob` |
| **Runs 对比** `RunsComparePage` | `metrics.json`, `performance_metrics.json` | PostgreSQL `pg_run` JOIN `pg_run_summary` |
| **风险** `RiskTaskList` | Mock 数据 | PostgreSQL `pg_risk_alert`（由规则层产出） |
| **Runs 列表 API** | `/trident-api/runs` | PostgreSQL `pg_run` |

API 前缀保持与 V3-ui 一致：`/trident-api/*`，由 BFF 查 PG/CH，不再读磁盘。

---

## 3. PostgreSQL 表结构

命名前缀 `pg_`。主键推荐 `BIGSERIAL`；业务键 `run_id` 与现目录名一致（如 `20260525_165211_benchmark_replay.yaml`）。

### 3.1 Run 与配置

#### `pg_run` — 运行实例

对应：`run_summary.txt`、`live_run_status.json`、Runs 列表。

```sql
CREATE TABLE pg_run (
  id                  BIGSERIAL PRIMARY KEY,
  run_id              VARCHAR(256) NOT NULL UNIQUE,
  profile             VARCHAR(32)  NOT NULL,     -- batch | replay | benchmark | viz-demo
  status              VARCHAR(16)  NOT NULL DEFAULT 'running',  -- running | finished | failed

  -- 输入
  input_source        VARCHAR(32)  NOT NULL,     -- csv | redis_stream | kafka
  mq_topic            VARCHAR(128),            -- suricata:cic_flow
  suricata_instance   VARCHAR(64),

  -- run_summary
  total_windows       INT,
  initial_learner_count INT,
  final_learner_count   INT,
  max_learner_count     INT,
  feature_dim           INT,
  rows_used             INT,

  -- live（流式 run 增量更新）
  live_windows_count  INT DEFAULT 0,
  live_rows_used      INT DEFAULT 0,
  live_learner_count  INT DEFAULT 0,

  benchmark_enabled   BOOLEAN DEFAULT FALSE,
  seed                INT,
  started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at         TIMESTAMPTZ,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pg_run_started ON pg_run(started_at DESC);
CREATE INDEX idx_pg_run_profile ON pg_run(profile);
CREATE INDEX idx_pg_run_status ON pg_run(status);
```

#### `pg_run_config` — 配置快照

对应：`config_snapshot.yaml`。

```sql
CREATE TABLE pg_run_config (
  run_id      VARCHAR(256) PRIMARY KEY REFERENCES pg_run(run_id) ON DELETE CASCADE,
  config_yaml TEXT NOT NULL,
  config_json JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pg_run_config_gin ON pg_run_config USING GIN (config_json);
```

#### `pg_run_summary` — Run 级指标（Runs 对比页）

对应：`metrics.json`、`performance_metrics.json` 摘要。

```sql
CREATE TABLE pg_run_summary (
  run_id              VARCHAR(256) PRIMARY KEY REFERENCES pg_run(run_id) ON DELETE CASCADE,
  risk_fpr            DOUBLE PRECISION,
  risk_fnr            DOUBLE PRECISION,
  windows_count       INT,
  new_learner_count   INT,
  avg_window_seconds  DOUBLE PRECISION,
  detect_seconds_total DOUBLE PRECISION,
  protocol_summary    JSONB,
  perf_json           JSONB,
  metrics_json        JSONB NOT NULL,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `pg_benchmark` / `pg_benchmark_stage`

对应：`trident_performance_benchmark.json`（benchmark profile）。

```sql
CREATE TABLE pg_benchmark (
  run_id                    VARCHAR(256) PRIMARY KEY REFERENCES pg_run(run_id) ON DELETE CASCADE,
  flow_count                INT,
  stream_flow_count         INT,
  wall_clock_sec            DOUBLE PRECISION,
  flows_per_sec_inference   DOUBLE PRECISION,
  flows_per_sec_e2e         DOUBLE PRECISION,
  qualification_detail      JSONB,
  stream_perf_stats         JSONB,
  raw_json                  JSONB NOT NULL,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE pg_benchmark_stage (
  id            BIGSERIAL PRIMARY KEY,
  run_id        VARCHAR(256) NOT NULL REFERENCES pg_benchmark(run_id) ON DELETE CASCADE,
  stage_key     VARCHAR(64) NOT NULL,
  duration_sec  DOUBLE PRECISION NOT NULL,
  UNIQUE (run_id, stage_key)
);

CREATE TABLE pg_benchmark_stage_resource (
  id                  BIGSERIAL PRIMARY KEY,
  run_id              VARCHAR(256) NOT NULL REFERENCES pg_benchmark(run_id) ON DELETE CASCADE,
  stage_key           VARCHAR(64) NOT NULL,
  process_cpu_seconds DOUBLE PRECISION,
  rss_peak_mb         DOUBLE PRECISION,
  gpu_peak_allocated_mb DOUBLE PRECISION,
  raw_json            JSONB,
  UNIQUE (run_id, stage_key)
);
```

---

### 3.2 学习器与定性（规则层）

#### `pg_learner` — 学习器主表

对应：audit JSON `learners[]` 顶层 + `learner_label_distribution.csv` 汇总。

```sql
CREATE TABLE pg_learner (
  id                  BIGSERIAL PRIMARY KEY,
  run_id              VARCHAR(256) NOT NULL REFERENCES pg_run(run_id) ON DELETE CASCADE,
  learner_name        VARCHAR(512) NOT NULL,
  flow_count          INT NOT NULL DEFAULT 0,
  attack_ratio        DOUBLE PRECISION,
  dominant_label      VARCHAR(512),
  dominant_ratio      DOUBLE PRECISION,
  is_benign           BOOLEAN,
  protocol_cluster_type VARCHAR(64),
  temporal_cluster_type VARCHAR(64),
  port_cluster_type   VARCHAR(64),
  risk_score          DOUBLE PRECISION,
  risk_band           VARCHAR(32),
  profile_json        JSONB,                    -- learner_label_distribution.csv 中未关系化的画像字段
  created_at_window   INT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, learner_name)
);
CREATE INDEX idx_pg_learner_run ON pg_learner(run_id);
CREATE INDEX idx_pg_learner_attack ON pg_learner(run_id, attack_ratio DESC);
CREATE INDEX idx_pg_learner_profile_gin ON pg_learner USING GIN (profile_json);
```

#### `pg_learner_profile_feature` — 学习器画像窄表

对应：`learner_label_distribution.csv` 中 `*_mean` / `*_std` / `*_cv`、协议、时序、端口等可排序字段。  
`pg_learner.profile_json` 保留无损快照，本表承接前端常用筛选、排序和横向对比。

```sql
CREATE TABLE pg_learner_profile_feature (
  id             BIGSERIAL PRIMARY KEY,
  run_id         VARCHAR(256) NOT NULL,
  learner_name   VARCHAR(512) NOT NULL,
  feature_key    VARCHAR(128) NOT NULL,
  feature_value  DOUBLE PRECISION,
  feature_text   TEXT,
  feature_group  VARCHAR(32),                  -- traffic | protocol | temporal | port | risk | meta
  FOREIGN KEY (run_id, learner_name) REFERENCES pg_learner(run_id, learner_name) ON DELETE CASCADE,
  UNIQUE (run_id, learner_name, feature_key)
);
CREATE INDEX idx_pg_profile_feature_key ON pg_learner_profile_feature(run_id, feature_key);
```

#### `pg_learner_label_stat` — 学习器内标签分布

```sql
CREATE TABLE pg_learner_label_stat (
  id            BIGSERIAL PRIMARY KEY,
  run_id        VARCHAR(256) NOT NULL,
  learner_name  VARCHAR(512) NOT NULL,
  label         VARCHAR(512) NOT NULL,
  count         INT NOT NULL,
  ratio         DOUBLE PRECISION,
  FOREIGN KEY (run_id, learner_name) REFERENCES pg_learner(run_id, learner_name) ON DELETE CASCADE,
  UNIQUE (run_id, learner_name, label)
);
```

#### `pg_learner_metric` — 22 项拓扑指标

对应：`learner_topology_metric_audit.json` → `learners[].metrics[]`。  
V3-ui `LearnerMetricAuditPanel` 直接读此表。

```sql
CREATE TABLE pg_learner_metric (
  id              BIGSERIAL PRIMARY KEY,
  run_id          VARCHAR(256) NOT NULL,
  learner_name    VARCHAR(512) NOT NULL,
  metric_key      VARCHAR(64) NOT NULL,
  metric_name     VARCHAR(128),
  metric_group    VARCHAR(32),
  raw_value       DOUBLE PRECISION NOT NULL,
  score_0_100     DOUBLE PRECISION,
  trait_axis      VARCHAR(32),
  trait_axis_label VARCHAR(32),
  strength_band   VARCHAR(16),
  strength_label  VARCHAR(16),
  semantic_tag    VARCHAR(128),
  semantic_text   TEXT,
  catalog_version INT NOT NULL DEFAULT 4,
  FOREIGN KEY (run_id, learner_name) REFERENCES pg_learner(run_id, learner_name) ON DELETE CASCADE,
  UNIQUE (run_id, learner_name, metric_key)
);
CREATE INDEX idx_pg_metric_run_learner ON pg_learner_metric(run_id, learner_name);
```

#### `pg_learner_hint` — 定性提示

对应：`qualitative_hints[]`。

```sql
CREATE TABLE pg_learner_hint (
  id            BIGSERIAL PRIMARY KEY,
  run_id        VARCHAR(256) NOT NULL,
  learner_name  VARCHAR(512) NOT NULL,
  hint_key      VARCHAR(64) NOT NULL,
  order_index   INT DEFAULT 0,
  severity      VARCHAR(16),
  hint_text     TEXT NOT NULL,
  FOREIGN KEY (run_id, learner_name) REFERENCES pg_learner(run_id, learner_name) ON DELETE CASCADE,
  UNIQUE (run_id, learner_name, hint_key)
);
```

#### `pg_learner_rule` — 参考规则匹配

对应：`reference_rules[]`；规则版本 `topology-family-v2`。  
后端计算、前端 V3-ui **只读展示**（与现 `learnerReferenceRules.ts` 职责分离：DB 存结果，前端不再本地 eval）。

```sql
CREATE TABLE pg_learner_rule (
  id              BIGSERIAL PRIMARY KEY,
  run_id          VARCHAR(256) NOT NULL,
  learner_name    VARCHAR(512) NOT NULL,
  rule_key        VARCHAR(64) NOT NULL,
  rule_name       VARCHAR(128) NOT NULL,
  tone            VARCHAR(16) NOT NULL,       -- benign | attack | caution
  match_level     VARCHAR(16) NOT NULL,       -- strong | weak | near
  evidence_met    INT NOT NULL,
  evidence_total  INT NOT NULL,
  evidence_json   JSONB,                      -- 命中指标、阈值、实际值，供 UI 解释与审计回放
  semantic        TEXT,
  rules_version   VARCHAR(32) NOT NULL DEFAULT 'topology-family-v2',
  FOREIGN KEY (run_id, learner_name) REFERENCES pg_learner(run_id, learner_name) ON DELETE CASCADE,
  UNIQUE (run_id, learner_name, rule_key)
);
CREATE INDEX idx_pg_rule_tone ON pg_learner_rule(tone, match_level);
CREATE INDEX idx_pg_rule_evidence_gin ON pg_learner_rule USING GIN (evidence_json);
```

#### `pg_learner_skipped` — 未导出审计的学习器

对应：audit JSON `learners_skipped[]`。

```sql
CREATE TABLE pg_learner_skipped (
  id                        BIGSERIAL PRIMARY KEY,
  run_id                    VARCHAR(256) NOT NULL REFERENCES pg_run(run_id) ON DELETE CASCADE,
  learner_name              VARCHAR(512) NOT NULL,
  reason                    TEXT NOT NULL,
  flow_count_joined         INT,
  label_distribution_samples INT
);
```

---

### 3.3 拓扑与大二进制产物

V3-ui `NetworkTopologyPanel` / `LearnerInternalTopologyPanel` 读 JSON 图结构。

#### `pg_artifact_blob`

```sql
CREATE TABLE pg_artifact_blob (
  id              BIGSERIAL PRIMARY KEY,
  run_id          VARCHAR(256) NOT NULL REFERENCES pg_run(run_id) ON DELETE CASCADE,
  artifact_type   VARCHAR(64) NOT NULL,
  artifact_key    VARCHAR(128) NOT NULL DEFAULT 'default',
  file_name       VARCHAR(256),
  content_json    JSONB,
  storage_uri     TEXT,
  byte_size       BIGINT,
  checksum_sha256 CHAR(64),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, artifact_type, artifact_key)
);
```

| `artifact_type` | 原文件 | V3-ui 用途 |
|-----------------|--------|------------|
| `dataset_topology` | `dataset_network_topology.json` | 总览数据集拓扑 |
| `learner_topology` | `learner_network_topology.json` | 学习器内外拓扑 |
| `decision_tree` | `decision_tree_visualization.json` | 决策树面板 |
| `feature_corr` | `learner_feature_attack_ratio_correlation.json` / `dataset_label_feature_attack_correlation.json` | 特征相关（用 `artifact_key` 区分 learner / dataset） |
| `creation_flow` | `learner_creation_flow_previews.json` | 建学习器预览 |

---

### 3.4 重叠 / 聚合（总览页）

#### `pg_learner_overlap`

对应：`debug_true_overlap_pairs.csv`。

```sql
CREATE TABLE pg_learner_overlap (
  id                  BIGSERIAL PRIMARY KEY,
  run_id              VARCHAR(256) NOT NULL REFERENCES pg_run(run_id) ON DELETE CASCADE,
  learner_a           VARCHAR(512) NOT NULL,
  learner_b           VARCHAR(512) NOT NULL,
  intersection_count  INT,
  union_count         INT,
  jaccard_acceptance  DOUBLE PRECISION,
  accept_rate_a_to_b  DOUBLE PRECISION,
  accept_rate_b_to_a  DOUBLE PRECISION
);
CREATE INDEX idx_pg_overlap_run ON pg_learner_overlap(run_id);
```

#### `pg_learner_aggregate`

对应：`learner_aggregated_distribution.csv`、`learner_aggregation_mapping.csv`。

```sql
CREATE TABLE pg_learner_aggregate (
  id                      BIGSERIAL PRIMARY KEY,
  run_id                  VARCHAR(256) NOT NULL REFERENCES pg_run(run_id) ON DELETE CASCADE,
  aggregate_name          VARCHAR(512) NOT NULL,
  member_count            INT,
  total_assigned_samples  INT,
  attack_ratio            DOUBLE PRECISION,
  members_json            JSONB
);
```

---

### 3.5 风险列表（V3-ui `/risk`）

将规则层 **attack + strong** 匹配映射为可运营风险条目（替代 mock）。

#### `pg_risk_alert`

对应：V3-ui `RiskItem`（`src/api/types.ts`）。

```sql
CREATE TABLE pg_risk_alert (
  id              BIGSERIAL PRIMARY KEY,
  run_id          VARCHAR(256) NOT NULL REFERENCES pg_run(run_id) ON DELETE CASCADE,
  learner_name    VARCHAR(512) NOT NULL,
  rule_key        VARCHAR(64),
  rule_match_id   BIGINT REFERENCES pg_learner_rule(id) ON DELETE SET NULL,
  subject_ip      INET,                          -- 从学习器拓扑 dominant host 提取
  name            VARCHAR(256) NOT NULL,         -- 规则名 / 学习器名
  trigger_time    TIMESTAMPTZ NOT NULL,
  description     TEXT,
  features        TEXT,                          -- 命中规则 semantic 拼接
  match_level     VARCHAR(16),
  risk_score      DOUBLE PRECISION,
  risk_band       VARCHAR(32),
  evidence_json   JSONB,
  status          VARCHAR(16) DEFAULT 'open',    -- open | acknowledged | closed
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, learner_name, rule_key)
);
CREATE INDEX idx_pg_risk_trigger ON pg_risk_alert(trigger_time DESC);
CREATE INDEX idx_pg_risk_run ON pg_risk_alert(run_id);
CREATE INDEX idx_pg_risk_evidence_gin ON pg_risk_alert USING GIN (evidence_json);
```

---

### 3.6 静态参考表

```sql
CREATE TABLE pg_ref_metric_catalog (
  metric_key      VARCHAR(64) PRIMARY KEY,
  metric_name     VARCHAR(128),
  metric_group    VARCHAR(32),
  trait_axis      VARCHAR(32),
  catalog_version INT NOT NULL,
  semantic_text   TEXT,
  active          BOOLEAN DEFAULT TRUE
);

CREATE TABLE pg_ref_rule_definition (
  rule_key        VARCHAR(64) PRIMARY KEY,
  rule_name       VARCHAR(128),
  tone            VARCHAR(16),
  rules_version   VARCHAR(32) NOT NULL,
  definition_json JSONB NOT NULL,
  active          BOOLEAN DEFAULT TRUE
);
```

---

## 4. ClickHouse 表结构

引擎默认：`MergeTree`，按 `(run_id, event_time)` 排序；生产可用 `ReplicatedMergeTree`。

### 4.1 `ch_flow_raw` — Suricata / MQ 原始流

**主流程入口表**：Suricata 提取时间戳、五元组、CIC 特征后写入（或 Trident 消费 MQ 时同步落库）。

```sql
CREATE TABLE ch_flow_raw (
  run_id          String,
  flow_uid        String,              -- 稳定流主键：Redis stream id / Kafka offset / run_id:row_index / hash
  source_flow_id  String,              -- Suricata Flow ID（若存在）
  row_index       Nullable(UInt64),     -- 离线 CSV / demo run 行号
  event_time      DateTime64(3),         -- 流时间戳
  ingest_time     DateTime64(3) DEFAULT now64(3),

  -- 五元组
  src_ip          IPv4,
  dst_ip          IPv4,
  src_port        UInt16,
  dst_port        UInt16,
  protocol        UInt8,                 -- 6=TCP 17=UDP

  -- 标签（Live 常无真值）
  label           String DEFAULT '0000|UNLABELED',

  -- 特征（compact_stats_no_env 约 35 维；稀疏列 + Map 二选一）
  feature_profile String DEFAULT 'compact_stats_no_env',
  features        Map(String, Float64),  -- 动态特征键值

  -- 溯源
  ingest_source   LowCardinality(String), -- suricata | csv_replay | redis_replay
  mq_topic        String,
  mq_message_id   String,
  suricata_event  String                 -- 原始 EVE JSON（可选压缩）
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (run_id, event_time, flow_uid)
TTL event_time + INTERVAL 90 DAY;
```

`flow_uid` 必须由写入端稳定生成，优先级建议：

1. Redis Stream：`{stream}:{message_id}`。
2. Kafka：`{topic}:{partition}:{offset}`。
3. 离线 CSV / demo：`{run_id}:{row_index}`。
4. 兜底：`sha256(run_id + timestamp + five_tuple + row_index)`。

批量 CSV 回放使用同一 schema，`ingest_source='csv_replay'`。

---

### 4.2 `ch_flow_assignment` — 流 → 学习器分配

Trident 推理完成后写入；对应 `sample_learner_assignments.csv`。

```sql
CREATE TABLE ch_flow_assignment (
  run_id            String,
  flow_uid          String,
  row_index         UInt64,              -- 兼容离线 CSV 行号
  event_time        DateTime64(3),
  assigned_learner  String,
  phase             Enum8('stream'=1, 'creation_fill'=2),
  window_index      UInt32,
  pred_loss         Nullable(Float64),   -- 重构误差（可选）
  threshold         Nullable(Float64),
  is_unknown        UInt8 DEFAULT 0,
  assignment_meta   String               -- JSON 字符串，保留 debug route / accepted_names 等可选信息
)
ENGINE = MergeTree()
PARTITION BY run_id
ORDER BY (run_id, event_time, flow_uid);
```

V3-ui 若需「单流下钻」，从此表按 `run_id + learner_name` 查；默认 UI 不展示全量流，仅聚合。

---

### 4.3 `ch_window_stats` — 窗口时序

对应：`learner_count_over_time.csv`；Live 模式每窗口 INSERT。

```sql
CREATE TABLE ch_window_stats (
  run_id            String,
  window_index      UInt32,
  window_left       UInt64,
  window_right      UInt64,
  window_end_time   DateTime64(3),
  learner_count     UInt32,
  unknown_buffer    UInt32,
  detect_ms         Float64,
  cluster_ms        Float64,
  create_learner_ms Float64,
  retrain_ms        Float64,
  window_total_ms   Float64,
  new_learner_count UInt32,
  incremental_update_count UInt32,
  created_at        DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
ORDER BY (run_id, window_index);
```

总览页 ECharts 曲线：`SELECT * FROM ch_window_stats WHERE run_id = ? ORDER BY window_index`。

---

### 4.4 `ch_flow_feature_flat` — 宽表（可选）

若 BI 需要固定列而非 Map，可从 `features` 物化视图展开为宽表（35 列），与 `trident_demo` 的 `compact_stats_no_env` 对齐。  
首版可用 Map，后续按 [`LEARNER_METRIC_AND_RULE_FORMULAS.md`](../LEARNER_METRIC_AND_RULE_FORMULAS.md) 列名加 MV。

---

### 4.5 ClickHouse 物化视图（规则层输入）

规则层在 PostgreSQL 侧计算，但 **指标原始统计** 可在 CH 按学习器预聚合后推送 PG：

```sql
CREATE MATERIALIZED VIEW ch_mv_learner_flow_stats
ENGINE = AggregatingMergeTree()
ORDER BY (run_id, assigned_learner)
AS SELECT
  run_id,
  assigned_learner,
  count() AS flow_count,
  uniqExact(dst_ip) AS dst_host_cnt,
  uniqExact(concat(toString(src_ip), ':', toString(src_port), '->', toString(dst_ip), ':', toString(dst_port))) AS edge_cnt
FROM ch_flow_assignment
JOIN ch_flow_raw USING (run_id, flow_uid)
GROUP BY run_id, assigned_learner;
```

完整 22 项拓扑指标仍在 Trident `qualification` 模块计算（需图结构），结果写 **PostgreSQL** `pg_learner_metric`。

---

## 5. 主流程 × 表写入顺序

```
1. Run 开始
   → INSERT pg_run (status=running)
   → INSERT pg_run_config

2. Suricata → MQ（每条流）
   → INSERT ch_flow_raw

3. Trident 消费 MQ（窗口循环）
   → 推理 / 建学习器 → UPSERT pg_learner
   → INSERT ch_flow_assignment（批量）
   → INSERT ch_window_stats
   → UPDATE pg_run.live_*

4. 窗口 / Run 级 Live flush
   → UPSERT pg_learner + pg_learner_profile_feature
   → DELETE+INSERT pg_learner_metric / pg_learner_hint / pg_learner_rule（该 run 快照）
   → UPSERT pg_artifact_blob（topology JSON，按 artifact_type + artifact_key）

5. Run 结束
   → UPDATE pg_run (status=finished, summary)
   → INSERT pg_run_summary, pg_benchmark, pg_benchmark_stage, pg_benchmark_stage_resource
   → UPSERT pg_risk_alert（由 pg_learner_rule attack+strong 生成，保留 rule_match_id / evidence_json）
```

---

## 6. 配置示例（trident_demo）

```yaml
storage:
  postgres:
    dsn: postgresql://trident:****@localhost:5432/trident_demo
  clickhouse:
    dsn: clickhouse://localhost:9000/trident_demo
  dual_write_disk: false          # 生产关闭磁盘
  ch_batch_size: 5000
  pg_flush_audit_interval_windows: 1
  ingest:
    mq_type: redis_stream         # redis_stream | kafka
    topic: suricata:cic_flow
```

---

## 7. BFF API 建议（供 V3-ui）

| 方法 | 路径 | 数据源 |
|------|------|--------|
| GET | `/trident-api/runs` | `pg_run` |
| GET | `/trident-api/runs/{id}` | `pg_run` + `pg_run_summary` |
| GET | `/trident-api/runs/{id}/windows` | `ch_window_stats` |
| GET | `/trident-api/runs/{id}/learners` | `pg_learner` |
| GET | `/trident-api/runs/{id}/learners/{name}/audit` | metric + hint + rule |
| GET | `/trident-api/runs/{id}/artifacts/{type}` | `pg_artifact_blob` |
| GET | `/trident-api/runs/compare` | `pg_run_summary` 批量 |
| GET | `/trident-api/risks` | `pg_risk_alert` |

---

## 8. 迁移路线

| 阶段 | 内容 |
|------|------|
| P0 | 建 PG 表 + CH `ch_flow_raw` / `ch_flow_assignment` / `ch_window_stats`；统一 `flow_uid` 生成 |
| P1 | Trident demo 双写；落 `pg_learner.profile_json` / `pg_learner_profile_feature`；V3-ui BFF 切 PG/CH |
| P2 | Live flush 幂等写 PG audit/rule/hint + CH 窗口 |
| P3 | `pg_risk_alert` 对接风险页；CSV 回放/import 工具 |
| P4 | 关磁盘产物，CH TTL + PG 归档 |

---

## 9. 相关文档

- Demo 主流程：[`PROJECT_GUIDE.md`](PROJECT_GUIDE.md)（若存在）
- V3-ui 数据类型：[`../V3-ui/src/modules/overview/types/learnerTopology.ts`](../V3-ui/src/modules/overview/types/learnerTopology.ts)
- 指标与规则公式：[`../LEARNER_METRIC_AND_RULE_FORMULAS.md`](../LEARNER_METRIC_AND_RULE_FORMULAS.md)
- 规则层设计：[`../docs/learner_topology_metric_audit_design.md`](../docs/learner_topology_metric_audit_design.md)
