# Trident Demo Redis 流式处理全链路说明

本文档只讨论基于 Redis 的流式处理链路，不展开 CSV 离线模式。重点是从 `tcpreplay` 到 `Suricata`，再到 `Redis Stream`，最后到 `Trident` 的完整时间线，以及每一步的时间消耗口径。

## 1. 这条链路的范围

完整链路是：

```text
pcap
  -> tcpreplay
  -> Suricata 解析
  -> Redis Stream 写入
  -> Trident 从 Redis 读取
  -> Trident 预处理 / 初始化 / 窗口推理 / 聚类 / 增量训练
  -> 结果导出 / benchmark / stress 汇总
```

这条链路里，时间不是单一数字，而是多个阶段叠加的结果。要看清性能，必须把“发送时间”“解析时间”“消费时间”“等待时间”“导出时间”分开看。

## 2. 入口配置

Redis 流式链路主要由这些配置控制：

- `trident_demo/stress/configs/e2e.yaml`
- `trident_demo/configs/replay.yaml`
- `trident_demo/configs/benchmark.yaml`

关键参数：

- `tcpreplay`：回放 pcap 的速度、循环次数、最小时长、接口。
- `suricata`：容器、网卡、是否重建、是否停止。
- `redis`：stream 名称、最大长度、idle timeout、max_messages。
- `trident`：Trident 的 profile、窗口大小、最大行数、超时。
- `runtime.perf_mode`：是否走真正的按窗口 Redis 流式消费。

## 3. 时间线总览

按一次完整 E2E Redis 流式实验看，时间线大致如下：

```text
T0  -> preflight
T1  -> 启动 Redis / Suricata
T2  -> baseline 采样
T3  -> 启动 Trident 后台线程
T4  -> tcpreplay 开始发送 pcap
T5  -> Suricata 开始解析并写 Redis
T6  -> Trident 开始从 Redis 取数据
T7  -> Trident 完成初始化学习器
T8  -> Trident 进入窗口式在线处理
T9  -> tcpreplay 结束
T10 -> Suricata 继续收尾解析
T11 -> Redis Stream 增长收敛
T12 -> Trident 完成剩余窗口处理
T13 -> 导出结果、benchmark、stress summary
T14 -> run 结束
```

这里有一个关键点：

- `tcpreplay` 的结束，不等于整条链路结束。
- `Suricata` 的解析结束，不等于 `Redis` 已经不再增长。
- `Trident` 的窗口处理结束，不等于结果文件已经写完。

## 4. 分阶段时间消耗

### 4.1 Preflight

阶段位置：

```text
run_stress()
  -> preflight()
```

作用：

- 检查 Docker 是否可用。
- 检查 `tcpreplay` 是否可用。
- 检查 Suricata 镜像是否存在。
- 检查 pcap、配置文件是否存在。
- 校验 Suricata 镜像动态库是否完整。

耗时特征：

- 通常是短时间阶段。
- 如果镜像检查或 `ldd` 探测较慢，会有一定额外开销。
- 它不是主瓶颈，但会进入总时长。

### 4.2 启动服务

阶段位置：

```text
start_services()
  -> docker compose up redis
  -> docker compose up suricata
```

作用：

- 启动 Redis 容器。
- 启动或重建 Suricata 容器。
- 等待 Redis 可连通。
- 清空 Redis Stream。

耗时特征：

- 受 Docker 启动速度影响。
- Suricata 容器重建时会更慢。
- 这部分属于链路准备时间，不是 Trident 计算时间。

### 4.3 Baseline 采样

阶段位置：

```text
baseline
```

作用：

- 在没有回放压力时采样 Redis 和 Docker 的空载状态。

耗时特征：

- 这段是人为等待。
- 主要用于后续对比，不代表有效处理能力。

### 4.4 tcpreplay 发送

阶段位置：

```text
run_replay_until_load()
  -> tcpreplay ...
```

作用：

- 把 pcap 里的包按指定速率发送到网卡。
- 触发 Suricata 抓包和解析。

关键耗时：

- `replay_seconds`
- `replay_send_total_seconds`

来源：

- `replay.log`
- `stress_summary.json.stages_seconds.tcpreplay`
- `stress_summary.json.derived_timing.replay_send_total_seconds`

这一步的含义：

- 它是输入压力，不是 Trident 处理能力。
- 发送越慢，后面的解析和消费也会被拉长。

### 4.5 Suricata 解析

阶段位置：

```text
tcpreplay
  -> Suricata 解析流量并写 Redis
```

作用：

- 从网卡读取流量。
- 按 Suricata 规则和 flow 引擎解析。
- 把解析后的流写入 Redis Stream。

关键耗时：

- `wait_after_replay`
- `suricata_parse_total_seconds`

来源：

- `wait_for_suricata_settle()`
- `stress_summary.json.derived_timing.suricata_parse_total_seconds`

为什么会有这段时间：

- pcap 发完后，Suricata 还会继续处理尾部流量。
- 有些 flow 需要等会话收尾、超时或缓冲刷新后才会写入 Redis。

这一步的特点：

- 它不是 tcpreplay 的发送时间。
- 它也不是 Trident 的计算时间。
- 它是上游“出流收尾时间”。

### 4.6 Redis Stream 积累

阶段位置：

```text
Suricata -> Redis Stream
```

作用：

- Redis 接收 Suricata 写入的 flow。
- Trident 从这里消费数据。

关键耗时：

- `xlen` 增长过程
- `redis_metrics.json` 的采样时间线

这一步的等待常见于：

- Suricata 还没写够。
- Redis 还在持续增长。
- Trident 在等目标窗口凑齐。

### 4.7 Trident 启动和初始学习器

阶段位置：

```text
run_pipeline()
  -> TridentStreamingExperiment.run()
  -> _load_dataset()
  -> _build_initial_learners()
```

作用：

- 读取 Redis stream。
- 生成 DataFrame。
- 做时间、标签、缺失值和特征预处理。
- 构建初始学习器。

这一步里常见的耗时指标可以直接按下面理解：

| 指标 | 含义 | 主要做什么 |
|---|---|---|
| `io_source_read` | 从输入源读取数据的时间 | 从 Redis 拉消息并转成 DataFrame，或者在其他模式下读取输入批次 |
| `io_preprocess` | 原始数据清洗整理的时间 | 补 `Label` / `Timestamp`、解析时间、排序、标签归一化、过滤、缺失值处理、全零规则过滤 |
| `io_feature_matrix` | 构建模型输入矩阵的时间 | 删除环境字段、选择数值特征、处理 `NaN/inf`、转成 `x_all` |
| `init_learners` | 训练初始学习器的时间 | 按标签分组、训练 AutoEncoder 或 IsolationForest、估计阈值、记录初始画像 |

关键耗时：

- `io_source_read`
- `io_preprocess`
- `io_feature_matrix`
- `init_learners`

初始化等待来源：

| 等待条件 | 含义 | 为什么要等 |
|---|---|---|
| `stream.init_ratio` | 先从输入中拿前一段数据作为初始化区间 | Trident 需要先有一批起始数据才能训练第一批学习器 |
| `init_known_mode=benign_only` | 初始化阶段只用良性样本 | 先建立“正常行为”基线，避免攻击样本污染初始模型 |
| `init_benign_year` | 只接受指定年份的良性样本 | 限定初始化数据来源，避免年份混杂导致分布不稳定 |
| `init_benign_count` | 至少要凑够这么多良性样本 | 数量不足时无法稳定训练初始良性学习器 |

更具体地说，初始化并不是“数据一到就立刻训练”，而是要按下面顺序满足条件：

```text
先到达 init_ratio 指定的初始化区间
  -> 再筛选 init_known_mode / init_benign_year
  -> 再检查 init_benign_count 是否足够
  -> 条件满足后才进入 init_learners
```

因此，这些等待时间通常会被算进 Trident 启动前半段的耗时里，但它们本质上是“等待初始化条件满足”，不是纯计算时间。

这段时间经常会被误认为“Trident 很慢”，但实际上很多时候是“初始化条件还没满足”。

### 4.8 窗口式在线处理

阶段位置：

```text
for window in stream:
  classify_batch()
  -> unknown 聚类
  -> 新学习器创建
  -> 增量重训练
  -> 写窗口统计
```

作用：

- 对每个窗口中的样本逐个分类。
- 收集 UNKNOWN。
- 触发 DBSCAN 聚类。
- 发现新类后创建 `NEW_*` 学习器。
- 对已有学习器做增量训练。

关键耗时：

- `stream_inference`
- `stream_cluster`
- `stream_create_learner`
- `stream_retrain`

这几个阶段的时间含义：

- `stream_inference`：对当前窗口所有样本做所有学习器的 loss 计算。
- `stream_cluster`：unknown buffer 达到阈值后做标准化和 DBSCAN。
- `stream_create_learner`：新类模型训练。
- `stream_retrain`：历史样本拼接后的增量训练和阈值刷新。

这一段通常是在线处理的核心耗时区。

### 4.9 等待时间

Redis 流式链路里除了计算，还有几类很重要的等待时间。

#### A. 上游等待

- tcpreplay 还没把流量发完。
- Suricata 还没把 flow 写完。
- Redis Stream 还没增长到目标值。

#### B. 窗口凑齐等待

- `stream.window_size` 还没攒满。
- `load_redis_flows()` / `iter_redis_flow_windows()` 还在等更多消息。

#### C. 初始化等待

- `init_ratio` 还没凑够。
- `init_known_mode=benign_only` 条件还没满足。

#### D. 算法条件等待

- `cluster_trigger_size` 还没到。
- `increment_min_samples` 还没到。
- `new_learner_cooldown_windows` 还没结束。

#### E. 读取阻塞等待

- `block_timeout_seconds`
- `idle_timeout_seconds`
- `wait_for_target_seconds`

这些等待通常会体现在：

- `wait_after_replay`
- `io_source_read`
- `runtime_fps_true`
- `wait_ratio`

它们不是单纯的 CPU 计算时间，但会计入整轮流程耗时。

## 5. 普通 Redis 和 perf_mode 的区别

### 5.1 普通 Redis 模式

流程：

```text
load_redis_flows()
  -> 先拉取一批消息到完整 DataFrame
  -> 统一预处理
  -> 构建完整 x_all
  -> 初始化学习器
  -> 按 window_size 切窗口
  -> 完整导出画像和 benchmark
```

特点：

- 更像“先汇总一批数据，再离线式地做在线模拟”。
- 会把 `io_source_read`、预处理、导出和窗口处理都算进去。
- 适合看完整 demo 的总成本。

### 5.2 `perf_mode` Redis

流程：

```text
iter_redis_flow_windows()
  -> 每次读取一个窗口
  -> 当前窗口立即预处理
  -> 当前窗口立即进入 Trident
  -> 不先构建完整离线批次
  -> 尽量少导出非核心产物
```

特点：

- 更接近真正的在线消费。
- 更容易暴露窗口等待、上游供给和增量训练成本。
- 适合看 Trident 真实在线吞吐。

### 5.3 两者时间口径差异

- 普通 Redis 的 `io_source_read` 往往包含批量拉取和部分等待。
- `perf_mode` 的 `io_source_read` 更接近按窗口消费的实时读取。
- 普通 Redis 会有更多导出时间。
- `perf_mode` 会尽量压缩导出时间，把重点放在 `stream_inference`、`stream_retrain`、`runtime_fps_true` 上。

## 6. 一次完整流程的时间线

把一次完整 Redis 流式实验按时间顺序压成一条线，可以这样理解：

```text
1. preflight 检查环境
2. 启动 Redis 和 Suricata
3. baseline 采样
4. Trident 后台线程启动
5. tcpreplay 开始回放
6. Suricata 开始产出 flow
7. Redis Stream 开始积累
8. Trident 读取 Redis，完成预处理
9. Trident 先构建初始学习器
10. Trident 进入窗口式分类
11. 未知流量进入聚类器
12. 发现新类则创建新学习器
13. 已接收样本触发增量重训练
14. tcpreplay 结束
15. Suricata 继续收尾解析
16. Redis 继续收敛增长
17. Trident 处理剩余窗口
18. 导出画像、指标、benchmark、stress summary
19. 结束
```

如果你要看“一次完整流程用了多少时间”，应该分成下面几个总账：

- `replay_send_total_seconds`
- `suricata_parse_total_seconds`
- `trident_analysis_total_seconds`
- `trident_pipeline_total_seconds`
- `trident_thread_runtime_seconds`
- `wait_ratio`

## 7. 如何读结果文件

压测后重点看这些文件：

- `stress_summary.json`
- `stress_summary.md`
- `redis_metrics.json`
- `docker_metrics.json`
- `suricata_metrics.json`
- `replay.log`
- `trident/<run_id>/trident_performance_benchmark.json`

关键字段：

- `derived_timing.replay_send_total_seconds`
- `derived_timing.suricata_parse_total_seconds`
- `derived_timing.trident_analysis_total_seconds`
- `derived_component_metrics.suricata.flow_fps_total`
- `derived_component_metrics.trident.runtime_fps_true`
- `derived_component_metrics.trident.wait_ratio`
- `derived_component_metrics.trident.stream_window_fps`

## 8. 结论

如果只看 Redis 流式链路，时间消耗可以拆成三层：

1. 上游发送和解析耗时
2. Trident 的读取、预处理、初始化、窗口处理耗时
3. 等待和导出耗时

真正最值得比较的 Trident 性能指标，不是单看总时长，而是分开看：

- `reported_fps_inference`
- `stream_window_fps`
- `runtime_fps_true`
- `wait_ratio`
- `trident_analysis_total_seconds`

这样才能判断是：

- 上游慢
- 还是窗口条件没满足
- 还是 Trident 自己的计算慢
- 还是导出太重
