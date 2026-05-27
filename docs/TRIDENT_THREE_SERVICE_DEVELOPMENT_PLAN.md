# Trident 三服务实时流处理产品开发计划

## 1. 背景

本计划面向一个独立于 `trident_demo` 的新产品实现。目标是将实时网络流量处理链路拆分为三个独立服务，形成可部署、可恢复、可观测的线上方案：

- `Suricata`：负责采集网络流量并产出 flow / CIC 特征
- `Redis`：负责实时消息缓冲、消费进度管理和 backlog 恢复
- `Trident`：负责持续消费实时流量，完成在线预处理、窗口推理、unknown 处理、聚类、新学习器创建和增量更新

本计划只覆盖核心产品链路，不包含可视化前端、测试脚本、压测控制器、demo 注入逻辑等外围内容。项目目标是保持代码结构纯净，便于后续独立部署和演进。

## 2. 目标

### 2.1 产品目标

1. 支持实时流量接入，不依赖离线 CSV 注入路径。
2. 将 Suricata、Redis、Trident 解耦为三个独立服务。
3. 完整复现 Trident 核心在线逻辑，而不是只保留 batch classify。
4. 将在线运行状态落到数据库，支持回溯、查询和状态刷新。
5. 保证服务可独立启动、独立重启、独立恢复。

### 2.2 技术目标

1. Trident 以 Redis Stream 作为唯一在线输入。
2. Trident 需要保留完整窗口链路：
   - 消费流量
   - runtime preprocessing
   - 特征矩阵构建
   - 初始学习器准备
   - batch 分类
   - unknown buffer
   - DBSCAN 聚类
   - 新学习器创建
   - 增量重训练
3. 数据层采用两张核心表：
   - `ch_flow`
   - `pg_learner`
4. 第一版不扩张到复杂派生表，先稳住主链路。

## 3. 范围说明

### 3.1 本期范围内

- Suricata 实时采集和写 Redis Stream
- Redis Stream 消费组、pending 恢复、ack 机制
- Trident 实时消费和在线处理
- `ch_flow` / `pg_learner` 写入
- Trident 结果输出流
- 基础运行指标和健康状态

### 3.2 本期不做

- 可视化前端
- 测试脚本和压测控制器
- demo 数据注入
- 与 `trident_demo` 的代码引用耦合
- 额外的派生查询表，除非是在线主链路必须

## 4. 总体架构

```text
Mirror Port / Gateway Traffic
  -> Suricata Service
      -> 提取 flow / CIC 特征
      -> 写入 Redis Stream

Redis Service
  -> 保存实时消息
  -> 负责 consumer group / backlog / pending recovery

Trident Service
  -> 持续消费 Redis Stream
  -> runtime preprocessing
  -> feature matrix
  -> 在线窗口处理
  -> assignment / alert / metric 输出
  -> 写入 ch_flow / pg_learner
```

三者必须是独立进程、独立配置、独立重启单元。Trident 不能假设 Redis 由自己创建，Suricata 也不能假设 Trident 已启动。

## 5. 服务职责

### 5.1 Suricata Service

职责：

- 接收镜像口、旁路点或网关流量
- 持续提取 flow / CIC 特征
- 将每条流写入 Redis Stream

输入：

- 网络流量

输出：

- `suricata:cic_flow`

要求：

1. 每条消息必须代表一个已形成的 flow feature record。
2. 字段尽量采用 CIC 风格命名。
3. 字段名不统一时，由 Trident 的 Redis loader 负责归一化。
4. Suricata 不负责在线推理，不负责数据库写入，不负责学习器状态管理。

### 5.2 Redis Service

职责：

- 作为 Suricata 和 Trident 之间的消息缓冲层
- 解耦生产速度和消费速度
- 保留消费进度和 backlog

建议的 stream：

```text
suricata:cic_flow
trident:assignments
trident:alerts
trident:metrics
```

关键要求：

1. 使用固定 Redis URL 和固定 stream key。
2. 使用 consumer group 管理 Trident 消费进度。
3. 支持 pending recovery 和重试。
4. 需要暴露 `XLEN`、`XPENDING`、consumer lag 等健康指标。
5. Redis 只做消息中转，不承担业务状态存储。

### 5.3 Trident Service

职责：

- 作为长期运行的独立在线消费者
- 持续读取 Redis Stream
- 执行实时预处理和在线推理
- 管理 unknown、cluster、新学习器、增量更新
- 写入数据库并输出运行结果

Trident 的核心要求不是“读到消息后分类”，而是完整复现实时窗口逻辑。必须包含：

1. Redis 消费
2. runtime preprocessing
3. 特征对齐和特征矩阵构建
4. 初始学习器创建
5. classify_batch
6. accepted / UNKNOWN 分流
7. unknown buffer
8. DBSCAN 聚类
9. 新学习器创建
10. 增量重训练
11. assignment / alert / metric 输出

## 6. 数据设计

### 6.1 `ch_flow`

`ch_flow` 用于保存每条实时流及 Trident 的分配结果。它既是流事实表，也是在线推理结果表。

核心字段：

- `session_id`
- `flow_uid`
- `event_time`
- `ingest_time`
- `src_ip`
- `dst_ip`
- `src_port`
- `dst_port`
- `protocol`
- `feature_profile`
- `features_json`
- `assigned_learner`
- `is_unknown`
- `window_index`
- `pred_loss`
- `threshold`
- `assignment_meta`
- `learner_snapshot_id`
- `learner_snapshot_version`
- `mq_type`
- `mq_topic`
- `mq_message_id`
- `source_flow_id`
- `raw_event`

设计原则：

1. 第一版把特征放在 `features_json` 中，避免频繁改表。
2. `flow_uid` 必须稳定，后续回溯、去重、补写都依赖它。
3. 原始流与分配结果优先放在同一张表，减少查询 join 成本。
4. 写入必须具备幂等性，避免重放导致重复污染。

`flow_uid` 建议优先采用：

1. `stream key + message id`
2. `topic + partition + offset`
3. `session_id + timestamp + five-tuple + mq_message_id` 的 hash 兜底

### 6.2 `pg_learner`

`pg_learner` 用于保存当前学习器状态、画像、规则和风险信息。它不是历史表，只保存当前快照。

核心字段：

- `session_id`
- `learner_name`
- `learner_status`
- `creation_window_index`
- `last_seen_window_index`
- `created_at`
- `last_seen_at`
- `updated_at`
- `flow_count`
- `assignment_share`
- `unknown_absorb_count`
- `protocol_cluster_type`
- `temporal_cluster_type`
- `port_cluster_type`
- `stability_score`
- `drift_score`
- `risk_score`
- `risk_band`
- `risk_reason`
- `profile_json`
- `metric_json`
- `rule_json`
- `topology_json`

设计原则：

1. `session_id + learner_name` 唯一定位一个学习器当前状态。
2. 复杂的画像、规则、拓扑信息优先保存在 JSONB 中。
3. `risk_score`、`risk_band`、`flow_count` 等高频筛选字段应列化。
4. Live flush 需要幂等更新，不应插入重复行。
5. 如需快速定位当前快照，可在 `pg_learner` 中维护 `current_snapshot_id` 和 `current_snapshot_version` 两个引用字段。

### 6.3 `pg_learner_snapshot`

`pg_learner_snapshot` 用于保存学习器的历史快照。它的职责不是表示当前状态，而是冻结某个时刻的学习器外观，供历史流回放、审计和对比使用。

核心语义：

- `pg_learner` 表示当前态
- `pg_learner_snapshot` 表示历史态
- `ch_flow` 只保存对某个快照的引用

建议字段：

- `snapshot_id`
- `session_id`
- `learner_name`
- `snapshot_version`
- `window_index`
- `snapshot_reason`
- `created_at`
- `profile_json`
- `metric_json`
- `rule_json`
- `topology_json`
- `risk_score`
- `risk_band`
- `risk_reason`
- `threshold`
- `model_state_hash`

设计原则：

1. 快照一旦生成就不可修改。
2. 同一个 `session_id + learner_name` 可以有多个快照版本。
3. 快照版本必须单调递增，便于回放和定位。
4. 快照生成频率应受事件驱动，不应按每条流生成。

建议的生成时机：

- 学习器创建
- 学习器合并
- 学习器退休
- 阈值变化
- 画像变化达到阈值
- 每个窗口结束后的 live flush

如果需要在 `ch_flow` 中做历史回放，建议增加下列引用字段：

- `learner_snapshot_id`
- `learner_snapshot_version`

这样前端在查询某条历史流时，可以直接定位到当时对应的学习器快照，而不是使用当前学习器状态回解释历史数据。

## 7. Trident 核心逻辑复现要求

Trident 必须完整保留实时流量处理链，不得只保留性能路径或分类路径。实现上应将原有“实验/性能路径”拆分为真正的线上引擎。

### 7.1 在线处理主流程

1. 启动 Trident 服务并生成 `session_id`
2. 连接 Redis consumer group
3. 按窗口消费流量
4. 对每条流执行 runtime preprocessing
5. 构建窗口特征矩阵并对齐维度
6. 初始化或恢复学习器状态
7. 调用 batch 推理
8. 将样本分发到：
   - accepted learner
   - unknown buffer
9. 对 unknown 进行聚类
10. 创建新学习器或更新现有学习器
11. 执行增量重训练
12. 将结果写入 `ch_flow` 和 `pg_learner`
13. 输出 assignment / alert / metric 到 Redis Stream

### 7.2 必须包含的状态能力

- consumer group 恢复
- pending recovery
- ack 策略
- graceful shutdown
- consumer lag 监控
- window 级别的状态推进
- 学习器生命周期管理

### 7.3 必须保留的算法环节

以下逻辑不能省略：

- `classify_batch`
- accepted / unknown 判定
- `tmagnifier.add_unknown`
- `pop_new_class_clusters`
- `_create_new_learners_from_clusters`
- `_maybe_recluster_small_learners`
- incremental update

## 8. 数据写入流程

### 8.1 流进入时

这一阶段的目标是先把实时流量可靠落到 `ch_flow`，再补充分配结果。不要把“消息读取”“特征清洗”“窗口推理”“结果回写”混成一段逻辑。

处理顺序建议固定为：

1. Trident 消费 Redis 消息。
2. 解析并归一化字段，补齐五元组、时间戳、特征集名称。
3. 生成或解析 `flow_uid`。
4. 写入 `ch_flow` 的基础流记录。
5. 保存 MQ 来源信息和原始事件。

写入原则：

- 第一次写入只保证原始事实和溯源信息存在。
- 如果窗口推理还没完成，`assigned_learner`、`is_unknown`、`pred_loss`、`threshold` 可以保持默认值。
- 同一条流重复消费时必须覆盖同一条记录，而不是插入新行。
- 字段清洗和归一化要集中在 loader 层，不要散落到推理逻辑里。

### 8.2 推理完成时

这一阶段发生在一个窗口的在线推理完成之后。它不是临时标记，而是窗口内样本的最终归属结果。

更新内容：

1. 完成窗口分配。
2. 按 `flow_uid` 批量回写 `ch_flow.assigned_learner`。
3. 回写 `ch_flow.is_unknown`。
4. 回写 `ch_flow.pred_loss`。
5. 回写 `ch_flow.threshold`。
6. 回写 `ch_flow.window_index`。
7. 将分类路径、候选学习器、拒绝原因、未知原因等补充到 `assignment_meta`。
8. 刷新对应学习器的累计统计。

`assignment_meta` 建议保持 JSON 字符串，用来承载不会频繁变更、但又需要保留的调试信息，例如：

- `accepted`
- `rejected`
- `margin`
- `unknown_reason`
- `cluster_id`
- `cluster_size`
- `rule_hit`

这样做的目的，是让第一版 schema 保持稳定，同时保留足够的在线排障信息。

### 8.3 学习器状态刷新时

这一阶段是 Live flush。它写的是“当前学习器状态快照”，不是历史流水。

刷新内容：

1. 重新计算学习器画像。
2. 重新计算规则、拓扑和风险。
3. 对 `pg_learner` 执行 upsert。
4. 更新 `profile_json`、`metric_json`、`rule_json`、`topology_json`。
5. 刷新 `risk_score`、`risk_band`、`risk_reason`。
6. 更新 `flow_count`、`assignment_share`、`unknown_absorb_count`、`last_seen_window_index`、`last_seen_at`、`updated_at`。

这里的写法必须是幂等的。相同 `session_id + learner_name` 的快照被多次刷新时，只能更新同一行，不能累积插入。

### 8.4 学习器快照写入时

快照写入和当前态刷新不是一回事。当前态刷新写 `pg_learner`，快照写 `pg_learner_snapshot`。

写入顺序建议为：

1. 在学习器创建、合并、退休、阈值变化或窗口 flush 时判断是否需要生成快照。
2. 生成新的 `snapshot_version`。
3. 将当时的 `profile_json`、`metric_json`、`rule_json`、`topology_json`、`risk_*`、`threshold` 冻结写入 `pg_learner_snapshot`。
4. 将该快照编号回填到 `pg_learner` 的当前引用字段，或者在应用层维持当前快照指针。
5. 如该学习器对应的流已落库，则在 `ch_flow` 中记录 `learner_snapshot_id` 和 `learner_snapshot_version`。

快照表的写入必须满足：

- 不更新已存在的历史行
- 不覆盖旧版本
- 不把历史表当成当前态表使用

### 8.5 流与快照的引用关系

历史流展示默认应基于入库时的学习器快照，而不是当前学习器状态。

推荐引用链：

```text
ch_flow -> learner_snapshot_id -> pg_learner_snapshot
```

如果前端查询一条历史流：

1. 先查 `ch_flow`
2. 再根据 `learner_snapshot_id` 或 `learner_snapshot_version` 查 `pg_learner_snapshot`
3. 使用该快照展示当时的画像、规则、拓扑和风险

这样可以保证：

- 历史结果可复现
- 解释口径一致
- 学习器演化不会污染历史视图

### 8.6 保存逻辑的分层

建议把 Trident 的持久化分成三层，不要把所有写逻辑堆在一个函数里：

1. **Ingest 层**
   - 负责把 Redis 消息转换成 `ch_flow` 基础记录
   - 负责 `flow_uid` 生成、字段归一化、原始事件保存

2. **Inference 层**
   - 负责窗口推理完成后的结果回写
   - 负责 `assigned_learner`、`is_unknown`、`pred_loss`、`threshold`、`assignment_meta`

3. **Snapshot 层**
   - 负责学习器快照刷新
   - 负责 `pg_learner` 的画像、风险、规则和拓扑更新

这种分层的好处是：

- 推理逻辑和持久化逻辑解耦
- 同一个窗口可以重放
- 崩溃后只需要重跑对应层，不需要重建整个流程

### 8.7 幂等与恢复策略

Trident 的写入策略要按“重复消息可恢复”来设计，而不是按“消息只会到一次”来设计。

推荐的恢复顺序是：

1. 先写 `ch_flow` 基础事实。
2. 再做窗口推理和结果回写。
3. 最后做 `pg_learner` 快照刷新。
4. 每一层完成后再 ack Redis 消息或窗口偏移。

如果 Trident 在任意阶段崩溃：

- 已写入的 `ch_flow` 基础事实应可被同一 `flow_uid` 覆盖。
- 未完成的窗口可以从 consumer group pending 中重新拉起。
- 已完成的 learner 快照可以重复刷新，不应产生重复行。

因此第一版不建议引入复杂的分布式事务。用“顺序写入 + 幂等 upsert + 可重放窗口”来控制一致性，更符合实时流系统的工程现实。

## 9. Trident 结果输出

Trident 需要向 Redis 输出三类结果流：

```text
trident:assignments
trident:alerts
trident:metrics
```

最小 assignment 结构：

```json
{
  "row_index": 123,
  "timestamp": "2026-05-26T10:15:23.123Z",
  "assigned_learner": "NEW_1",
  "is_unknown": false,
  "run_id": "trident-prod-20260526-001"
}
```

这些输出不属于可视化层，而是在线运行链路的一部分。它们应当能直接回溯到 `flow_uid`、`session_id` 和窗口编号。

## 10. 基础 API 接口

这一组接口只做最小框架，优先服务于运行状态查询和在线数据读取。后续如果出现明确的写入控制、告警确认、任务调度需求，再单独扩展，不要一开始把接口做宽。

### 10.1 设计原则

1. 接口只围绕 `ch_flow`、`pg_learner` 和运行状态展开。
2. 默认只做读取接口，不把业务控制面做复杂。
3. 所有列表接口支持 `session_id` 过滤和分页。
4. 详细对象接口只返回当前快照，不返回历史累积。
5. 接口响应保持统一结构，便于后续扩展。

建议统一响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

### 10.2 最小接口集合

#### 1. 健康检查

- `GET /api/v1/health`

用途：

- 判断 Trident 服务是否存活
- 判断 Redis 和数据库连接是否可用

返回内容：

- 服务状态
- `session_id`
- Redis 连接状态
- 数据库连接状态

#### 2. 运行概览

- `GET /api/v1/runtime/summary`

用途：

- 获取当前运行会话的基础概览

返回内容：

- `session_id`
- 当前窗口号
- 已消费流量数
- unknown 数量
- 学习器数量
- Redis backlog 概览
- 最近一次刷新时间

#### 3. 流量列表

- `GET /api/v1/flows`

用途：

- 查询 `ch_flow`
- 用于按时间、学习器、unknown 状态回看流量

支持参数：

- `session_id`
- `window_index`
- `learner_name`
- `is_unknown`
- `time_from`
- `time_to`
- `limit`
- `cursor`

返回内容：

- 流量事实记录
- 分配结果
- 溯源字段

#### 4. 学习器列表

- `GET /api/v1/learners`

用途：

- 查询 `pg_learner`
- 用于查看当前学习器集合和风险概览

支持参数：

- `session_id`
- `learner_status`
- `risk_band`
- `limit`
- `cursor`

返回内容：

- 学习器名称
- 状态
- 风险分数
- 流量规模
- 最近活跃窗口

#### 5. 学习器详情

- `GET /api/v1/learners/{learner_name}`

用途：

- 查看某个学习器的当前快照

返回内容：

- 基础状态字段
- `profile_json`
- `metric_json`
- `rule_json`
- `topology_json`
- 风险解释

#### 6. 学习器关联流量

- `GET /api/v1/learners/{learner_name}/flows`

用途：

- 查看某个学习器最近关联的流量样本

支持参数：

- `session_id`
- `limit`
- `cursor`

返回内容：

- 对应 `ch_flow` 的流记录
- 当前窗口号
- unknown 标记

### 10.3 接口边界说明

1. 这些接口只读数据库和运行状态，不直接触发在线训练逻辑。
2. 如果后续需要手动 flush、手动重算、暂停/恢复等控制能力，再单独新增控制类接口。
3. 不建议第一版开放过多写接口，避免把运行时操作和业务数据查询混在一起。

## 11. 开发阶段规划

### P0：骨架与数据契约

目标：

- 建立独立项目结构
- 定义三服务契约
- 固定 stream key、consumer group、消息字段
- 建立 `ch_flow` 和 `pg_learner` 的建表方案

交付标准：

- 三服务边界清晰
- 消息格式稳定
- 数据库 schema 可直接部署

### P1：实时接入打通

目标：

- Suricata 写 Redis
- Trident 读 Redis
- Trident 能完成基础窗口处理和最小分配

交付标准：

- 消息可持续流入
- Trident 可持续消费
- 结果能写回 `ch_flow`

### P2：完整在线逻辑

目标：

- 完整复现 Trident 在线窗口处理
- 支持 unknown 聚类、新学习器创建和增量更新
- 写出 assignment / alert / metric

交付标准：

- 不再只是 `classify_batch`
- 在线逻辑可长期运行
- 学习器状态可以更新和刷新

### P3：稳定性和恢复

目标：

- consumer group 恢复
- pending 重放
- graceful shutdown
- backlog 可观测

交付标准：

- Trident 重启后可继续消费
- Suricata 短暂中断不影响整体系统
- Redis backlog 可观察、可诊断

### P4：状态快照和风险刷新

目标：

- 定期 live flush `pg_learner`
- 刷新画像、指标、规则、拓扑、风险

交付标准：

- `pg_learner` 反映当前学习器真实状态
- 风险字段可用于后续查询和处置

## 12. 实施原则

1. 只围绕三服务构建，不把外围工具混入主仓库核心路径。
2. Trident 的在线引擎应独立成模块，不继续挂在实验路径中。
3. 第一版优先保证写入稳定和逻辑完整，不优先追求大而全 schema。
4. 所有状态更新都要可幂等重放。
5. Redis 是消息层，不是状态层。
6. `ch_flow` 和 `pg_learner` 是第一版的中心，不要过早扩表。

## 13. 风险与注意事项

### 12.1 代码边界风险

如果直接复用 `trident_demo` 里的目录结构，后续会把实验代码和产品代码混在一起。新项目应该重新组织模块边界，允许复制实现，但不要继续引用原仓库内部路径。

### 12.2 在线逻辑缩水风险

最常见的问题是把 Trident 缩减成“消费 Redis 后做一次分类”。这会丢失 unknown、聚类、新学习器和增量更新，和真实在线系统不是一回事。实现时必须把完整窗口链路补齐。

### 12.3 幂等和重放风险

Redis consumer group 会带来重试、pending、重复投递。数据库写入必须能识别重复流和重复快照，尤其是 `ch_flow` 和 `pg_learner`。

### 12.4 数据模型膨胀风险

第一版不要把所有窗口统计、告警、会话都拆成多张表。先保住核心链路，等查询模式稳定后再派生扩展表。

### 12.5 运行恢复风险

Trident 重启、Suricata 中断、Redis backlog 激增都是必然会发生的场景。开发时必须把恢复策略作为一等需求，而不是附属问题。

## 14. 结论

本计划的核心目标是建立一个独立、可持续运行的实时流处理产品：

- Suricata 负责采集和写入
- Redis 负责缓冲和恢复
- Trident 负责完整在线推理和学习器生命周期管理

第一版的成败标准不是界面是否完善，而是三服务链路是否稳定闭环，Trident 是否真正复现了实时流量处理逻辑，`ch_flow` 和 `pg_learner` 是否能够准确承载在线事实与状态。
