# Three-Service Streaming Architecture

本文档描述目标线上架构：Suricata、Redis、Trident 三个独立服务协作完成实时流式检测。

## 1. 目标架构

线上应拆成三个独立服务：

```text
Switch / Mirror Port
  -> Suricata Service
      -> 捕获流量
      -> 提取 CIC / flow 特征
      -> 写 Redis Stream

Redis Service
  -> 保存 Suricata 产出的 flow feature stream
  -> 提供 consumer group / backlog / pending 恢复能力

Trident Service
  -> 持续消费 Redis Stream
  -> runtime preprocessing
  -> feature matrix
  -> Trident online processing
  -> 输出 assignment / alert / metric
```

这个架构中，`stress/controller.py` 只应该作为实验压测工具，不应该代表线上部署方式。

## 2. 服务职责

### 2.1 Suricata Service

职责：

- 部署在交换机镜像口、网关、旁路采集点或等价位置。
- 持续采集网络流量。
- 生成 flow / CIC 特征。
- 将特征写入 Redis Stream。

输入：

```text
network interface / mirror traffic
```

输出：

```text
Redis Stream: suricata:cic_flow
```

消息要求：

- 每条消息代表一个已经形成的 flow feature record。
- 字段应尽量使用 CIC 风格字段名。
- 如果字段名不同，Trident Redis loader 会做常见别名归一化。

### 2.2 Redis Service

职责：

- 作为 Suricata 和 Trident 之间的消息缓冲层。
- 解耦 Suricata 产出速度和 Trident 消费速度。
- 暴露 backlog、pending、stream length 等健康指标。

建议 stream：

```text
suricata:cic_flow       # Suricata -> Trident 输入
trident:assignments     # Trident 输出样本归属，可选
trident:alerts          # Trident 输出告警，可选
trident:metrics         # Trident 输出运行指标，可选
```

生产建议：

- 使用固定 Redis URL。
- 使用固定 stream key。
- 使用 consumer group 管理 Trident 消费进度。
- 监控 `XLEN`、`XPENDING`、内存和 Redis ops。

### 2.3 Trident Service

职责：

- 作为独立消费者长期运行。
- 从 Redis Stream 读取 Suricata 写入的 flow feature。
- 执行 runtime preprocessing。
- 执行 Trident 在线处理。
- 输出最小运行指标和检测结果。

当前入口：

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

默认行为：

- 不启动 Redis。
- 不启动 Suricata。
- 不做 CSV 注入。
- 只连接配置中的 Redis。

如果为了本地 demo 需要自动启动 Redis，可以显式使用：

```bash
python3 -m trident_demo online --start-redis
```

## 3. 当前代码如何映射到三服务架构

### 3.1 Suricata

当前仓库中的 E2E 压测会通过 `stress/controller.py` 启动 Suricata 容器并回放 pcap。

线上架构中，这部分应该从 Trident demo 中拆出去，作为独立 Suricata 服务部署和运维。

当前 demo 仍保留 stress：

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

它的用途是压测和验证，不是生产启动方式。

### 3.2 Redis

当前 `online` 入口默认认为 Redis 已经存在：

```text
input.redis.url = redis://127.0.0.1:6379/0
input.redis.key = suricata:cic_flow
```

这符合三服务架构：Trident 不负责创建 Redis，只负责连接 Redis。

### 3.3 Trident

当前新增的 `online` 入口是 Trident 独立服务的第一阶段实现：

```text
trident_demo/cli.py
  -> trident_demo/runtime/online_runner.py
  -> PipelineRunner(no_inject=true)
  -> TridentStreamingExperiment
  -> _run_perf_mode_redis_stream()
```

它已经具备：

- 独立 Redis 连接。
- 按窗口读取 Redis Stream。
- runtime preprocessing。
- 特征矩阵构建和维度对齐。
- 初始学习器创建。
- 窗口推理。
- 最小 benchmark 输出。

它尚未完全具备：

- 完整 UNKNOWN 聚类。
- `NEW_*` 新学习器创建。
- 增量重训练。
- 服务化结果输出 stream。
- 长期运行下的 pending recovery / ack 策略完善。

## 4. 当前 online 流程

```text
Trident online command
  -> 读取 online.yaml
  -> 连接独立 Redis
  -> 跳过 CSV 注入
  -> Redis Stream 按窗口读取
  -> runtime preprocessing
  -> feature matrix
  -> 初始化 learner
  -> classify_batch()
  -> 输出 performance_summary / benchmark
```

当前 online 流程的核心定位：

```text
独立 Trident Redis consumer + 在线推理性能路径
```

它现在已经接入完整 Trident 算法窗口闭环，但仍保留在
`pipeline/experiment.py` 内，尚未进一步拆成独立 `runtime/engine.py`。

## 5. 与真实需求的差距

真实需求是：

```text
Trident 从 Redis 中获取流量进行解析走完全部流程
```

这里的“全部流程”应包括：

- Redis 消费。
- runtime preprocessing。
- 特征对齐。
- 初始学习器。
- 窗口推理。
- UNKNOWN buffer。
- DBSCAN 聚类。
- 新学习器创建。
- 增量重训练。
- 结果输出。

当前 online 已经通过 `_process_stream_windows()` 复用旧 `run()` 的完整窗口循环，以上流程都能在 Redis 窗口中执行。仍需继续改造的是代码归属：完整窗口引擎还在 `pipeline/experiment.py`，没有独立成纯线上 `runtime/engine.py`。

## 6. 下一步必须改的核心点

### 6.1 抽出 TridentOnlineEngine

建议新增：

```text
trident_demo/runtime/engine.py
```

目标接口：

```python
engine.process_window(window_df, window_x, offset)
```

该接口应包含当前普通 `run()` 中的完整窗口逻辑：

- `classify_batch`
- accepted / UNKNOWN 分发
- `tmagnifier.add_unknown`
- `pop_new_class_clusters`
- `_create_new_learners_from_clusters`
- `_maybe_recluster_small_learners`
- incremental update
- minimal metrics emit

### 6.2 把 online 从 perf path 改成 full runtime path

当前：

```text
_run_perf_mode_redis_stream()
  -> classify_batch only
```

目标：

```text
_run_online_redis_stream()
  -> engine.process_window()
```

### 6.3 增加结果输出流

建议输出：

```text
trident:assignments
trident:alerts
trident:metrics
```

最小 assignment 结构：

```json
{
  "row_index": 123,
  "timestamp": "...",
  "assigned_learner": "NEW_1",
  "is_unknown": false,
  "run_id": "..."
}
```

### 6.4 固化 Redis consumer group

生产需要配置：

```yaml
input:
  redis:
    consumer_group: trident-online
    consumer_name: trident-01
    ack: true
```

并补充：

- pending message recovery。
- graceful shutdown。
- consumer lag metrics。

## 7. 合理部署形态

示例：

```text
suricata-cic.service
  -> writes Redis stream suricata:cic_flow

redis.service
  -> owns stream and backlog

trident-online.service
  -> python3 -m trident_demo online --config /etc/trident/online.yaml
```

三者独立启动、独立重启、独立监控。

如果 Trident 重启：

- Suricata 不受影响。
- Redis 继续积压。
- Trident 恢复后继续消费。

如果 Suricata 短暂中断：

- Redis 不受影响。
- Trident 等待新消息或处理 backlog。

如果 Trident 处理慢：

- Redis backlog 上升。
- 通过 `XLEN` / `XPENDING` 可观测。

## 8. 当前结论

当前代码已经向三服务架构迈出关键一步：

- `online` 入口默认不启动 Redis。
- `online.yaml` 表达 Trident 独立消费者配置。
- runtime preprocessing 已与实验采样逻辑分开。
- online Redis window loop 已调用完整 Trident 窗口处理逻辑。

目前已经满足“Trident 从 Redis 获取流量并走完算法流程”的基本需求。

剩余核心缺口是工程分层：

```text
完整窗口处理仍位于 pipeline/experiment.py，没有独立成 runtime/engine.py
```

下一步应优先实现：

```text
TridentOnlineEngine.process_window()
```

然后让 `online` 从“推理性能路径”升级为“完整线上处理路径”。
